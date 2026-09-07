import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "ai-usage"
  ipcTarget: ""

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color surface: Color.popups.background
  readonly property color track: Style.selectedFillFor(foreground, Color.accent)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string home: Quickshell.env("HOME") || ""
  readonly property string collectorPath: Qt.resolvedUrl("collector.py").toString().replace(/^file:\/\//, "")
  readonly property string folderPickerPath: Qt.resolvedUrl("folder_picker.py").toString().replace(/^file:\/\//, "")

  property var cache: ({ schemaVersion: 1, accounts: [], error: "" })
  readonly property var accounts: cache && Array.isArray(cache.accounts) ? cache.accounts : []
  property int selectedTabIndex: 0
  readonly property bool summaryView: selectedTabIndex === 0
  readonly property int accountIndex: Math.max(0, selectedTabIndex - 1)
  readonly property var account: !summaryView && accounts.length > 0
    ? accounts[Math.min(accountIndex, accounts.length - 1)]
    : null
  property double nowMs: Date.now()
  property bool refreshQueued: false
  property bool refreshQueuedForce: false
  property double lastHoverRefreshMs: 0
  property bool editingSettings: false
  property string editingProfileId: ""
  property string draftProfileName: ""
  property bool settingsMigrationComplete: false
  property bool draftPrivacyModeEnabled: true
  property bool draftSleepModeEnabled: true
  property string draftCodexProfilesRoot: "~/.codex-profiles"
  property string draftClaudeProfileMode: "Single account"
  property string draftClaudeProfileRoot: "~/.claude"
  property string draftClaudeProfilesRoot: "~/.claude-profiles"
  property string draftRefreshMode: "Scheduled"
  property int draftRefreshIntervalMin: 15
  property int draftHoverCooldownSec: 60
  property string folderPickerTarget: "codex"
  property string settingsError: ""
  property string bridgeMessage: ""

  readonly property int refreshIntervalSec: Math.max(30, Number(setting("refreshIntervalSec", 900)))
  readonly property string codexProfilesRoot: String(
    setting("codexProfilesRoot", setting("profilesRoot", "~/.codex-profiles")) || "~/.codex-profiles"
  ).trim()
  readonly property string claudeProfileMode: String(setting("claudeProfileMode", "Single account") || "Single account")
  readonly property string claudeProfileRoot: String(setting("claudeProfileRoot", "~/.claude") || "~/.claude").trim()
  readonly property string claudeProfilesRoot: String(
    setting("claudeProfilesRoot", "~/.claude-profiles") || "~/.claude-profiles"
  ).trim()
  readonly property string activeClaudeProfilesRoot: claudeProfileMode === "Multiple accounts"
    ? claudeProfilesRoot : claudeProfileRoot
  readonly property var profileNames: normalizedProfileNames(setting("profileNames", ({})))
  readonly property string refreshMode: String(setting("refreshMode", "Scheduled") || "Scheduled")
  readonly property int hoverCooldownSec: Math.max(30, Number(setting("hoverCooldownSec", 60)))
  readonly property bool refreshOnHover: refreshMode === "On hover/open" || refreshMode === "Both"
  readonly property bool refreshOnSchedule: refreshMode === "Scheduled" || refreshMode === "Both"
  readonly property bool privacyModeEnabled: switchEnabled(setting("privacyMode", "On"))
  readonly property bool sleepModeEnabled: switchEnabled(setting("sleepMode", "Off"))
  readonly property int sleepStartMinute: clockMinutes(setting("sleepStart", "17:00"), 17 * 60)
  readonly property int sleepEndMinute: clockMinutes(setting("sleepEnd", "07:30"), 7 * 60 + 30)
  readonly property bool sleepModeActive: sleepModeEnabled && sleepModeAt(nowMs)
  readonly property bool alarming: {
    for (var accountIndex = 0; accountIndex < accounts.length; accountIndex++) {
      var limits = accounts[accountIndex].limits || []
      for (var limitIndex = 0; limitIndex < limits.length; limitIndex++)
        if (Number(limits[limitIndex].remainingPercent || 0) <= 10) return true
    }
    return false
  }

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function clamp(value, minimum, maximum) { return Math.max(minimum, Math.min(maximum, value)) }

  function hasSetting(key) {
    return settings && typeof settings === "object"
      && Object.prototype.hasOwnProperty.call(settings, key)
  }

  function cleanText(value, fallback) {
    var text = String(value === undefined || value === null ? (fallback || "") : value)
      .replace(/[\x00-\x1f\x7f]/g, "").substring(0, 256)
    return text || String(fallback || "").substring(0, 256)
  }

  function normalizedProfileNames(raw) {
    var result = {}
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return result
    var count = 0
    for (var key in raw) {
      if (count >= 64) break
      var id = cleanText(key, "")
      var name = cleanText(raw[key], "").trim().substring(0, 48)
      if (id !== "" && name !== "") {
        result[id] = name
        count++
      }
    }
    return result
  }

  function displayProfileName(value) {
    if (!value) return ""
    var id = cleanText(value.id, "")
    return id !== "" && profileNames[id]
      ? String(profileNames[id])
      : defaultProfileName(value)
  }

  function defaultProfileName(value) {
    if (!value) return ""
    return cleanText(value.label || value.id, value.provider === "claude" ? "Claude" : "Codex")
  }

  function claudeModeArgument(value) {
    return String(value || claudeProfileMode) === "Multiple accounts" ? "multiple" : "single"
  }

  function percent(value) {
    var number = Number(value)
    return isFinite(number) ? clamp(Math.round(number), 0, 100) : 0
  }

  function epoch(value) {
    var number = Number(value)
    return isFinite(number) && number >= 0 ? Math.floor(number) : null
  }

  function collectorCommand(arguments, duration) {
    var command = [
      "/usr/bin/timeout", "--signal=TERM", "--kill-after=2s", duration,
      "/usr/bin/python3", "-I", collectorPath
    ]
    return command.concat(arguments)
  }

  function switchEnabled(value) {
    if (value === true) return true
    var text = String(value || "").trim().toLowerCase()
    return text === "on" || text === "true" || text === "yes" || text === "1"
  }

  function clockMinutes(value, fallback) {
    var match = String(value || "").trim().match(/^([01]?\d|2[0-3]):([0-5]\d)$/)
    if (!match) return fallback
    return Number(match[1]) * 60 + Number(match[2])
  }

  function clockText(minutes) {
    var hours = Math.floor(minutes / 60)
    var remainder = minutes % 60
    return String(hours).padStart(2, "0") + ":" + String(remainder).padStart(2, "0")
  }

  function expandedProfilesPath(value) {
    var path = String(value || "").trim()
    if (path === "~") return home
    if (path.startsWith("~/")) return home + path.substring(1)
    return path
  }

  function browseProfilesRoot(target) {
    if (folderPickerProcess.running) return
    folderPickerTarget = target
    var currentPath = codexProfilesRootField.text || codexProfilesRoot
    if (target === "claude-single")
      currentPath = claudeProfileRootField.text || claudeProfileRoot
    else if (target === "claude-multiple")
      currentPath = claudeProfilesRootField.text || claudeProfilesRoot
    folderPickerProcess.command = [
      "/usr/bin/python3",
      "-I",
      folderPickerPath,
      expandedProfilesPath(currentPath)
    ]
    folderPickerProcess.running = true
  }

  function installClaudeBridge() {
    if (claudeBridgeProcess.running) return
    bridgeMessage = ""
    settingsError = ""
    var multiple = draftClaudeProfileMode === "Multiple accounts"
    var profileRoot = multiple
      ? String(claudeProfilesRootField.text || claudeProfilesRoot).trim()
      : String(claudeProfileRootField.text || claudeProfileRoot).trim()
    claudeBridgeProcess.command = collectorCommand([
      "--claude-profiles-root", profileRoot,
      "--claude-profile-mode", claudeModeArgument(draftClaudeProfileMode),
      "--install-claude-bridge"
    ], "15s")
    claudeBridgeProcess.running = true
  }

  function sleepModeAt(milliseconds) {
    if (!sleepModeEnabled) return false
    var date = new Date(milliseconds)
    var minute = date.getHours() * 60 + date.getMinutes()
    if (sleepStartMinute === sleepEndMinute) return false
    if (sleepStartMinute < sleepEndMinute)
      return minute >= sleepStartMinute && minute < sleepEndMinute
    return minute >= sleepStartMinute || minute < sleepEndMinute
  }

  function persistSettings(values) {
    if (!bar || !bar.shell || typeof bar.shell.updateEntryInline !== "function") {
      settingsError = "Could not save widget settings"
      return false
    }
    var entry = { id: moduleName }
    for (var key in settings) if (key !== "id") entry[key] = settings[key]
    for (var valueKey in values) entry[valueKey] = values[valueKey]
    settings = entry
    bar.shell.updateEntryInline(moduleName, entry)
    return true
  }

  function openSettings() {
    cancelProfileNameEdit(false)
    draftPrivacyModeEnabled = privacyModeEnabled
    draftSleepModeEnabled = sleepModeEnabled
    draftCodexProfilesRoot = codexProfilesRoot
    draftClaudeProfileMode = claudeProfileMode
    draftClaudeProfileRoot = claudeProfileRoot
    draftClaudeProfilesRoot = claudeProfilesRoot
    draftRefreshMode = refreshMode
    draftRefreshIntervalMin = Math.max(1, Math.round(refreshIntervalSec / 60))
    draftHoverCooldownSec = hoverCooldownSec
    settingsError = ""
    bridgeMessage = ""
    editingSettings = true
    Qt.callLater(function() {
      codexProfilesRootField.text = codexProfilesRoot
      claudeProfileModeField.value = claudeProfileMode
      claudeProfileRootField.text = claudeProfileRoot
      claudeProfilesRootField.text = claudeProfilesRoot
      refreshModeField.value = refreshMode
      refreshIntervalField.value = Math.max(1, Math.round(refreshIntervalSec / 60))
      hoverCooldownField.value = hoverCooldownSec
      sleepStartField.text = clockText(sleepStartMinute)
      sleepEndField.text = clockText(sleepEndMinute)
      codexProfilesRootField.selectAll()
      codexProfilesRootField.forceActiveFocus()
    })
  }

  function closeSettings(restoreFocus) {
    editingSettings = false
    settingsError = ""
    bridgeMessage = ""
    if (restoreFocus !== false)
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function toggleSettings() {
    if (editingSettings) closeSettings(true)
    else openSettings()
  }

  function saveSettings() {
    var codexRoot = String(codexProfilesRootField.text || "").trim()
    var claudeSingleRoot = String(claudeProfileRootField.text || "").trim()
    var claudeMultipleRoot = String(claudeProfilesRootField.text || "").trim()
    var start = clockMinutes(sleepStartField.text, -1)
    var end = clockMinutes(sleepEndField.text, -1)
    if (codexRoot === "" || claudeSingleRoot === "" || claudeMultipleRoot === "") {
      settingsError = "Choose the OpenAI and Claude profile locations"
      return
    }
    if (codexRoot.length > 4096 || claudeSingleRoot.length > 4096 || claudeMultipleRoot.length > 4096) {
      settingsError = "Profiles folder path is too long"
      return
    }
    var codexPathValid = codexRoot.charAt(0) === "/" || codexRoot === "~" || codexRoot.startsWith("~/")
    var claudeSingleValid = claudeSingleRoot.charAt(0) === "/" || claudeSingleRoot === "~" || claudeSingleRoot.startsWith("~/")
    var claudeMultipleValid = claudeMultipleRoot.charAt(0) === "/" || claudeMultipleRoot === "~" || claudeMultipleRoot.startsWith("~/")
    if (!codexPathValid || !claudeSingleValid || !claudeMultipleValid) {
      settingsError = "Use an absolute path or a path starting with ~/"
      return
    }
    if (start < 0 || end < 0) {
      settingsError = "Use 24-hour times such as 17:00 or 07:30"
      return
    }
    if (start === end) {
      settingsError = "Start and end times must be different"
      return
    }
    var profileRootChanged = codexRoot !== codexProfilesRoot
      || claudeSingleRoot !== claudeProfileRoot
      || claudeMultipleRoot !== claudeProfilesRoot
      || draftClaudeProfileMode !== claudeProfileMode
    var privacyModeChanged = draftPrivacyModeEnabled !== privacyModeEnabled
    if (persistSettings({
      codexProfilesRoot: codexRoot,
      claudeProfileMode: draftClaudeProfileMode,
      claudeProfileRoot: claudeSingleRoot,
      claudeProfilesRoot: claudeMultipleRoot,
      refreshMode: draftRefreshMode,
      refreshIntervalSec: draftRefreshIntervalMin * 60,
      hoverCooldownSec: draftHoverCooldownSec,
      privacyMode: draftPrivacyModeEnabled ? "On" : "Off",
      sleepMode: draftSleepModeEnabled ? "On" : "Off",
      sleepStart: clockText(start),
      sleepEnd: clockText(end)
    })) {
      closeSettings(true)
      if (profileRootChanged || privacyModeChanged) Qt.callLater(function() { refreshNow(true) })
    }
  }

  function migrateSettings() {
    if (settingsMigrationComplete || !bar || !bar.shell
        || typeof bar.shell.updateEntryInline !== "function") return
    var values = {}
    var changed = false
    if (!hasSetting("codexProfilesRoot")) {
      values.codexProfilesRoot = String(setting("profilesRoot", "~/.codex-profiles"))
      changed = true
    }
    if (!hasSetting("claudeProfileMode")) {
      var oldClaudeRoot = hasSetting("claudeProfilesRoot")
        ? String(settings.claudeProfilesRoot || "~/.claude") : "~/.claude"
      values.claudeProfileMode = "Single account"
      values.claudeProfileRoot = oldClaudeRoot
      values.claudeProfilesRoot = "~/.claude-profiles"
      changed = true
    } else {
      if (!hasSetting("claudeProfileRoot")) {
        values.claudeProfileRoot = "~/.claude"
        changed = true
      }
      if (!hasSetting("claudeProfilesRoot")) {
        values.claudeProfilesRoot = "~/.claude-profiles"
        changed = true
      }
    }
    if (!hasSetting("refreshMode")) {
      values.refreshMode = "Scheduled"
      changed = true
    }
    if (!hasSetting("hoverCooldownSec")) {
      values.hoverCooldownSec = 60
      changed = true
    }
    if (!hasSetting("profileNames")) {
      values.profileNames = {}
      changed = true
    }
    if (changed) {
      if (persistSettings(values)) settingsMigrationComplete = true
    } else {
      settingsMigrationComplete = true
    }
  }

  function beginProfileNameEdit(value) {
    var id = cleanText(value && value.id, "")
    if (id === "") return
    editingSettings = false
    editingProfileId = id
    draftProfileName = displayProfileName(value)
  }

  function cancelProfileNameEdit(restoreFocus) {
    editingProfileId = ""
    draftProfileName = ""
    if (restoreFocus !== false)
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function saveProfileName(value) {
    var id = cleanText(value && value.id, "")
    if (id === "" || id !== editingProfileId) return
    var names = {}
    for (var existing in profileNames) names[existing] = profileNames[existing]
    var name = cleanText(draftProfileName, "").trim().substring(0, 48)
    if (name === "" || name === defaultProfileName(value)) delete names[id]
    else names[id] = name
    if (persistSettings({ profileNames: names })) cancelProfileNameEdit()
  }

  function handleTimeFieldKey(event, otherField) {
    if (event.key === Qt.Key_Escape) {
      closeSettings(true)
      event.accepted = true
    } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
      otherField.selectAll()
      otherField.forceActiveFocus()
      event.accepted = true
    }
  }

  function selectTab(index) {
    var count = accounts.length + 1
    selectedTabIndex = ((index % count) + count) % count
  }

  function preferredLimit(value) {
    var limits = value && value.limits ? value.limits : []
    for (var i = 0; i < limits.length; i++)
      if (/5\s*(hour|hr)/i.test(String(limits[i].name || ""))) return limits[i]
    for (var j = 0; j < limits.length; j++)
      if (/week/i.test(String(limits[j].name || ""))) return limits[j]
    return limits.length > 0 ? limits[0] : null
  }

  function parseCache(content) {
    try {
      var source = String(content || "")
      if (source.length === 0 || source.length > 524288) return
      var parsed = JSON.parse(source)
      if (!parsed || parsed.schemaVersion !== 1 || !Array.isArray(parsed.accounts)) return
      var cleanAccounts = []
      for (var accountIndex = 0; accountIndex < Math.min(parsed.accounts.length, 64); accountIndex++) {
        var account = parsed.accounts[accountIndex]
        if (!account || typeof account !== "object") continue
        var cleanLimits = []
        var limits = Array.isArray(account.limits) ? account.limits : []
        for (var limitIndex = 0; limitIndex < Math.min(limits.length, 8); limitIndex++) {
          var limit = limits[limitIndex]
          if (!limit || typeof limit !== "object") continue
          cleanLimits.push({
            name: cleanText(limit.name, "Usage"),
            remainingPercent: percent(limit.remainingPercent),
            usedPercent: percent(limit.usedPercent),
            resetsAt: epoch(limit.resetsAt)
          })
        }
        var cleanResets = []
        var resets = Array.isArray(account.resets) ? account.resets : []
        for (var resetIndex = 0; resetIndex < Math.min(resets.length, 16); resetIndex++) {
          var reset = resets[resetIndex]
          if (!reset || typeof reset !== "object") continue
          cleanResets.push({ title: cleanText(reset.title, "Rate-limit reset"), expiresAt: epoch(reset.expiresAt) })
        }
        var credits = null
        if (account.credits && typeof account.credits === "object") {
          credits = {
            remainingPercent: percent(account.credits.remainingPercent),
            used: account.credits.used === null || account.credits.used === undefined
              ? null : cleanText(account.credits.used, ""),
            limit: account.credits.limit === null || account.credits.limit === undefined
              ? null : cleanText(account.credits.limit, ""),
            resetsAt: epoch(account.credits.resetsAt)
          }
        }
        cleanAccounts.push({
          id: cleanText(account.id, "Codex"),
          label: cleanText(account.label || account.id, "Codex"),
          provider: cleanText(account.provider, "codex"),
          providerLabel: cleanText(account.providerLabel, "OpenAI"),
          ready: account.ready === true,
          error: cleanText(account.error, ""),
          limits: cleanLimits,
          credits: credits,
          resets: cleanResets,
          email: cleanText(account.email, ""),
          plan: cleanText(account.plan, ""),
          updatedAtMs: epoch(account.updatedAtMs) || 0
        })
      }
      cache = {
        schemaVersion: 1,
        fetchedAtMs: epoch(parsed.fetchedAtMs) || 0,
        error: cleanText(parsed.error, ""),
        accounts: cleanAccounts
      }
      nowMs = Date.now()
      if (selectedTabIndex > accounts.length) selectedTabIndex = accounts.length
    } catch (error) {
      console.warn("ai-usage", "Ignoring invalid cache", error)
    }
  }

  function refreshNow(force, interactive) {
    var requestedForce = force === true
    nowMs = Date.now()
    if (!requestedForce && interactive !== true && sleepModeAt(nowMs)) return
    if (refreshProcess.running) {
      refreshQueued = true
      refreshQueuedForce = refreshQueuedForce || requestedForce
      return
    }
    refreshQueued = false
    refreshQueuedForce = false
    var arguments = [
      "--codex-profiles-root", codexProfilesRoot,
      "--claude-profiles-root", activeClaudeProfilesRoot,
      "--claude-profile-mode", claudeModeArgument(claudeProfileMode),
      "--json"
    ]
    if (!privacyModeEnabled) arguments.push("--show-identity")
    if (requestedForce) arguments.push("--force")
    refreshProcess.command = collectorCommand(arguments, "50s")
    refreshProcess.running = true
  }

  function hoverRefresh() {
    if (!refreshOnHover || refreshProcess.running) return
    var current = Date.now()
    var fetchedAt = Number(cache && cache.fetchedAtMs ? cache.fetchedAtMs : 0)
    var newest = Math.max(lastHoverRefreshMs, fetchedAt)
    if (newest > 0 && current - newest < hoverCooldownSec * 1000) return
    lastHoverRefreshMs = current
    refreshNow(false, true)
  }

  function ageText(milliseconds) {
    if (!(milliseconds >= 0)) return "unknown"
    var seconds = Math.floor(milliseconds / 1000)
    if (seconds < 10) return "just now"
    if (seconds < 60) return seconds + "s ago"
    var minutes = Math.floor(seconds / 60)
    if (minutes < 60) return minutes + "m ago"
    var hours = Math.floor(minutes / 60)
    if (hours < 24) return hours + "h " + (minutes % 60) + "m ago"
    return Math.floor(hours / 24) + "d ago"
  }

  function lastFetchText() {
    var fetchedAt = Number(cache && cache.fetchedAtMs ? cache.fetchedAtMs : 0)
    if (!(fetchedAt > 0)) return "Never fetched"
    var stamp = Qt.formatDateTime(new Date(fetchedAt), "HH:mm:ss")
    return "Last fetched " + stamp + " · " + ageText(Math.max(0, nowMs - fetchedAt))
  }

  function refreshIntervalText() {
    if (refreshIntervalSec % 60 === 0) return (refreshIntervalSec / 60) + "m"
    return refreshIntervalSec + "s"
  }

  function durationText(epochSeconds) {
    var target = Number(epochSeconds || 0) * 1000
    if (!(target > 0)) return ""
    var milliseconds = target - nowMs
    if (milliseconds <= 0) return "now"
    var minutes = Math.floor(milliseconds / 60000)
    var hours = Math.floor(minutes / 60)
    var days = Math.floor(hours / 24)
    if (days > 0) return days + "d " + (hours % 24) + "h"
    if (hours > 0) return hours + "h " + (minutes % 60) + "m"
    return Math.max(1, minutes) + "m"
  }

  function resetText(epochSeconds) {
    var duration = durationText(epochSeconds)
    return duration === "" ? "" : "Resets in " + duration
  }

  function remainingColor(remaining) {
    var value = Number(remaining || 0)
    if (value <= 10) return root.urgent
    if (value <= 25) return Color.accent
    return root.foreground
  }

  function accountMeta(value) {
    if (!value) return ""
    var parts = [String(value.providerLabel || (value.provider === "claude" ? "Claude" : "OpenAI"))]
    if (!privacyModeEnabled && value.email) parts.push(String(value.email))
    if (!privacyModeEnabled && value.plan) parts.push(String(value.plan))
    var updatedAt = Number(value.updatedAtMs || 0)
    if (value.provider === "claude" && updatedAt > 0)
      parts.push("usage " + ageText(Math.max(0, nowMs - updatedAt)))
    return parts.join(" · ")
  }

  function refreshBehaviorText() {
    if (refreshMode === "On hover/open")
      return "OpenAI refresh on hover/open · " + hoverCooldownSec + "s cooldown"
    if (refreshMode === "Both") return "OpenAI every " + refreshIntervalText() + " and on hover/open"
    return "OpenAI auto-refresh every " + refreshIntervalText()
  }

  function resetSummary(value) {
    var resets = value && Array.isArray(value.resets) ? value.resets : []
    if (resets.length === 0) return "No reset available"
    return resets.length + " reset" + (resets.length === 1 ? "" : "s") + " available"
  }

  Component.onCompleted: {
    Qt.callLater(function() { migrateSettings() })
    cacheReadProcess.running = true
  }

  onBarChanged: if (bar) Qt.callLater(function() { migrateSettings() })

  Component.onDestruction: {
    if (cacheReadProcess.running) cacheReadProcess.running = false
    if (refreshProcess.running) refreshProcess.running = false
    if (folderPickerProcess.running) folderPickerProcess.running = false
    if (claudeBridgeProcess.running) claudeBridgeProcess.running = false
  }

  onOpenedChanged: {
    if (opened) {
      nowMs = Date.now()
      hoverRefresh()
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    } else {
      if (editingSettings) closeSettings(false)
      if (editingProfileId !== "") cancelProfileNameEdit(false)
    }
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: root.refreshOnSchedule
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refreshNow(false)
  }

  Timer {
    interval: 10000
    running: root.opened
    repeat: true
    onTriggered: root.nowMs = Date.now()
  }

  Timer {
    id: sleepClock
    interval: 60000
    running: root.sleepModeEnabled
    repeat: true
    onTriggered: {
      var wasSleeping = root.sleepModeActive
      root.nowMs = Date.now()
      if (root.refreshOnSchedule && wasSleeping && !root.sleepModeAt(root.nowMs)) root.refreshNow(false)
    }
  }

  Process {
    id: cacheReadProcess
    running: false
    command: root.collectorCommand(
      root.privacyModeEnabled
        ? ["--cached", "--json"]
        : ["--cached", "--json", "--show-identity"],
      "5s"
    )

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.parseCache(text)
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") console.warn("ai-usage cache", text.trim())
    }
  }

  Process {
    id: folderPickerProcess
    running: false

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var selectedPath = text.trim()
        if (selectedPath === "") return
        var target = codexProfilesRootField
        if (root.folderPickerTarget === "claude-single") target = claudeProfileRootField
        else if (root.folderPickerTarget === "claude-multiple") target = claudeProfilesRootField
        target.text = selectedPath
        target.selectAll()
        target.forceActiveFocus()
      }
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") console.warn("ai-usage folder picker", text.trim())
    }
  }

  Process {
    id: claudeBridgeProcess
    running: false

    onExited: function(exitCode) {
      if (exitCode === 0) Qt.callLater(function() { root.refreshNow(true) })
    }

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") root.bridgeMessage = text.trim()
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") root.settingsError = text.trim()
    }
  }

  Process {
    id: refreshProcess
    running: false

    onExited: function(exitCode) {
      if (exitCode !== 0) console.warn("ai-usage", "Collector exited with", exitCode)
      if (root.refreshQueued) {
        var force = root.refreshQueuedForce
        root.refreshQueued = false
        root.refreshQueuedForce = false
        Qt.callLater(function() { root.refreshNow(force) })
      }
    }

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.parseCache(text)
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") console.warn("ai-usage", text.trim())
    }
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󱚣"
    active: root.alarming
    tooltipText: root.sleepModeActive && root.refreshOnSchedule
      ? "AI usage · OpenAI checks paused · " + root.lastFetchText()
      : "AI usage · " + root.lastFetchText()
    onTooltipHoveredChanged: if (tooltipHovered) root.hoverRefresh()
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton || buttonCode === Qt.MiddleButton) root.refreshNow(true)
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(410))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight, Style.space(590))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: root.editingSettings || root.editingProfileId !== ""
      onMoveRequested: function(dx, dy) {
        if (dx !== 0) root.selectTab(root.selectedTabIndex + dx)
        if (dy !== 0)
          contentScroll.contentY = root.clamp(contentScroll.contentY + dy * Style.space(52), 0,
            Math.max(0, contentScroll.contentHeight - contentScroll.height))
      }
      onActivateRequested: root.refreshNow(true)
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) { if (text === "r" || text === "R") root.refreshNow(true) }

      Flickable {
        id: contentScroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: contentColumn
          width: contentScroll.width
          spacing: Style.space(10)

          Row {
            width: parent.width
            spacing: Style.space(12)

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "󱚣"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
            }

            Column {
              width: Math.max(0, parent.width - x - settingsButton.width - parent.spacing)
              spacing: Style.space(2)

              Text {
                textFormat: Text.PlainText
                text: root.summaryView
                  ? "AI usage"
                  : root.displayProfileName(root.account)
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
              }

              Text {
                textFormat: Text.PlainText
                width: parent.width
                text: root.summaryView
                  ? "Preferred limit for every provider profile"
                  : root.accountMeta(root.account)
                visible: text !== ""
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }
            }

            PanelActionButton {
              id: settingsButton
              anchors.verticalCenter: parent.verticalCenter
              iconText: "󰒓"
              tooltipText: root.editingSettings ? "Close settings" : "Settings"
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.subtitle
              size: Style.space(28)
              bordered: true
              hasCursor: root.editingSettings
              onClicked: root.toggleSettings()
            }
          }

          BorderSurface {
            visible: root.editingSettings
            width: parent.width
            implicitHeight: settingsColumn.implicitHeight + Style.space(22)
            color: root.alpha(root.foreground, 0.035)
            borderSpec: Border.flat(root.alpha(root.foreground, 0.14), 1)
            radius: Style.cornerRadius

            Column {
              id: settingsColumn
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(11)
              spacing: Style.space(10)

              Row {
                width: parent.width
                spacing: Style.space(6)

                PanelSectionHeader {
                  width: Math.max(0, parent.width - openAiHelpButton.width - parent.spacing)
                  text: "OPENAI SETTINGS"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                }

                PanelActionButton {
                  id: openAiHelpButton
                  iconText: "?"
                  tooltipText: "OpenAI reads Codex auth.json profiles. API usage can refresh on hover/open, on a schedule, or both."
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  fontSize: Style.font.caption
                  size: Style.space(22)
                  bordered: true
                }
              }

              Row {
                width: parent.width
                spacing: Style.space(8)

                TextField {
                  id: codexProfilesRootField
                  width: Math.max(0, parent.width - browseCodexProfilesButton.width - parent.spacing)
                  placeholderText: "~/.codex-profiles"
                  foreground: root.foreground
                  accent: Color.accent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  onTextChanged: root.draftCodexProfilesRoot = text
                  onAccepted: root.saveSettings()
                  Keys.onPressed: function(event) { root.handleTimeFieldKey(event, sleepStartField) }
                }

                Button {
                  id: browseCodexProfilesButton
                  width: codexProfilesRootField.implicitHeight
                  height: codexProfilesRootField.implicitHeight
                  iconText: "󰉋"
                  tooltipText: folderPickerProcess.running ? "Folder picker open" : "Choose folder"
                  bordered: true
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  iconSize: Style.font.icon
                  horizontalPadding: 0
                  verticalPadding: 0
                  enabled: !folderPickerProcess.running
                  onClicked: root.browseProfilesRoot("codex")
                }
              }

              Dropdown {
                id: refreshModeField
                width: parent.width
                label: "API refresh behavior"
                value: root.draftRefreshMode
                options: ["On hover/open", "Scheduled", "Both"]
                foreground: root.foreground
                accent: Color.accent
                fontFamily: root.fontFamily
                onChanged: function(value) { root.draftRefreshMode = value }
              }

              NumberField {
                id: refreshIntervalField
                visible: root.draftRefreshMode !== "On hover/open"
                label: "Schedule interval (minutes)"
                value: root.draftRefreshIntervalMin
                from: 1
                to: 60
                stepSize: 1
                foreground: root.foreground
                accent: Color.accent
                fontFamily: root.fontFamily
                onModified: function(value) { root.draftRefreshIntervalMin = value }
              }

              NumberField {
                id: hoverCooldownField
                visible: root.draftRefreshMode !== "Scheduled"
                label: "Hover cooldown (seconds)"
                value: root.draftHoverCooldownSec
                from: 30
                to: 3600
                stepSize: 30
                foreground: root.foreground
                accent: Color.accent
                fontFamily: root.fontFamily
                onModified: function(value) { root.draftHoverCooldownSec = value }
              }

              Row {
                width: parent.width
                spacing: Style.space(6)

                PanelSectionHeader {
                  width: Math.max(0, parent.width - claudeHelpButton.width - parent.spacing)
                  text: "CLAUDE SETTINGS"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                }

                PanelActionButton {
                  id: claudeHelpButton
                  iconText: "?"
                  tooltipText: "Claude usage comes from Claude Code's official status line after you send a message. OpenAI refresh settings do not request Claude usage."
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  fontSize: Style.font.caption
                  size: Style.space(22)
                  bordered: true
                }
              }

              Dropdown {
                id: claudeProfileModeField
                width: parent.width
                label: "Account setup"
                value: root.draftClaudeProfileMode
                options: ["Single account", "Multiple accounts"]
                foreground: root.foreground
                accent: Color.accent
                fontFamily: root.fontFamily
                onChanged: function(value) { root.draftClaudeProfileMode = value }
              }

              Row {
                visible: root.draftClaudeProfileMode === "Single account"
                width: parent.width
                spacing: Style.space(8)

                TextField {
                  id: claudeProfileRootField
                  width: Math.max(0, parent.width - browseClaudeProfileButton.width - parent.spacing)
                  placeholderText: "~/.claude"
                  foreground: root.foreground
                  accent: Color.accent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  onTextChanged: root.draftClaudeProfileRoot = text
                  onAccepted: root.saveSettings()
                  Keys.onPressed: function(event) { root.handleTimeFieldKey(event, codexProfilesRootField) }
                }

                Button {
                  id: browseClaudeProfileButton
                  width: claudeProfileRootField.implicitHeight
                  height: claudeProfileRootField.implicitHeight
                  iconText: "󰉋"
                  tooltipText: folderPickerProcess.running ? "Folder picker open" : "Choose folder"
                  bordered: true
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  iconSize: Style.font.icon
                  horizontalPadding: 0
                  verticalPadding: 0
                  enabled: !folderPickerProcess.running
                  onClicked: root.browseProfilesRoot("claude-single")
                }
              }

              Row {
                visible: root.draftClaudeProfileMode === "Multiple accounts"
                width: parent.width
                spacing: Style.space(8)

                TextField {
                  id: claudeProfilesRootField
                  width: Math.max(0, parent.width - browseClaudeProfilesButton.width - parent.spacing)
                  placeholderText: "~/.claude-profiles"
                  foreground: root.foreground
                  accent: Color.accent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  onTextChanged: root.draftClaudeProfilesRoot = text
                  onAccepted: root.saveSettings()
                  Keys.onPressed: function(event) { root.handleTimeFieldKey(event, codexProfilesRootField) }
                }

                Button {
                  id: browseClaudeProfilesButton
                  width: claudeProfilesRootField.implicitHeight
                  height: claudeProfilesRootField.implicitHeight
                  iconText: "󰉋"
                  tooltipText: folderPickerProcess.running ? "Folder picker open" : "Choose folder"
                  bordered: true
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  iconSize: Style.font.icon
                  horizontalPadding: 0
                  verticalPadding: 0
                  enabled: !folderPickerProcess.running
                  onClicked: root.browseProfilesRoot("claude-multiple")
                }
              }

              Button {
                width: parent.width
                text: claudeBridgeProcess.running ? "Enabling…" : "Enable official Claude usage capture"
                iconText: "󰄬"
                iconSpinning: claudeBridgeProcess.running
                enabled: !claudeBridgeProcess.running
                bordered: true
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                onClicked: root.installClaudeBridge()
              }

              Text {
                visible: root.bridgeMessage !== ""
                width: parent.width
                textFormat: Text.PlainText
                text: root.bridgeMessage
                color: Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }

              PanelSectionHeader {
                text: "PRIVACY"
                foreground: root.foreground
                fontFamily: root.fontFamily
              }

              Toggle {
                width: parent.width
                label: "Hide account details"
                description: "Show profile names without email or subscription."
                foreground: root.foreground
                accent: Color.accent
                fontFamily: root.fontFamily
                checked: root.draftPrivacyModeEnabled
                onClicked: root.draftPrivacyModeEnabled = !root.draftPrivacyModeEnabled
              }

              PanelSectionHeader {
                text: "SLEEP SCHEDULE"
                foreground: root.foreground
                fontFamily: root.fontFamily
              }

              Toggle {
                width: parent.width
                label: "Pause scheduled OpenAI checks"
                description: "Hover/open and manual refreshes remain available."
                foreground: root.foreground
                accent: Color.accent
                fontFamily: root.fontFamily
                checked: root.draftSleepModeEnabled
                onClicked: root.draftSleepModeEnabled = !root.draftSleepModeEnabled
              }

              Row {
                width: parent.width
                spacing: Style.space(10)

                Column {
                  width: (parent.width - parent.spacing) / 2
                  spacing: Style.space(5)

                  Text {
                    textFormat: Text.PlainText
                    text: "FROM"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }

                  TextField {
                    id: sleepStartField
                    width: parent.width
                    placeholderText: "17:00"
                    maximumLength: 5
                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                    foreground: root.foreground
                    accent: Color.accent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    onAccepted: root.saveSettings()
                    Keys.onPressed: function(event) { root.handleTimeFieldKey(event, sleepEndField) }
                  }
                }

                Column {
                  width: (parent.width - parent.spacing) / 2
                  spacing: Style.space(5)

                  Text {
                    textFormat: Text.PlainText
                    text: "UNTIL"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }

                  TextField {
                    id: sleepEndField
                    width: parent.width
                    placeholderText: "07:30"
                    maximumLength: 5
                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                    foreground: root.foreground
                    accent: Color.accent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    onAccepted: root.saveSettings()
                    Keys.onPressed: function(event) { root.handleTimeFieldKey(event, sleepStartField) }
                  }
                }
              }

              Text {
                visible: root.settingsError !== ""
                width: parent.width
                textFormat: Text.PlainText
                text: root.settingsError
                color: root.urgent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }

              Item {
                width: parent.width
                height: settingsActions.implicitHeight

                Row {
                  id: settingsActions
                  anchors.right: parent.right
                  spacing: Style.space(8)

                  Button {
                    text: "Cancel"
                    bordered: true
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    onClicked: root.closeSettings(true)
                  }

                  Button {
                    text: "Save"
                    iconText: "󰄬"
                    bordered: true
                    selected: true
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    onClicked: root.saveSettings()
                  }
                }
              }
            }
          }

          Row {
            id: viewSwitch
            visible: root.accounts.length > 0
            width: parent.width
            spacing: Style.spacing.sm

            readonly property real tabHeight: Style.space(30)
            readonly property real summaryWidth: Style.space(34)
            readonly property real accountWidth: root.accounts.length > 0
              ? (width - summaryWidth - spacing * root.accounts.length) / root.accounts.length
              : 0

            Button {
              width: viewSwitch.summaryWidth
              height: viewSwitch.tabHeight
              iconText: "󰄧"
              tooltipText: "Summary"
              selected: root.summaryView
              bordered: true
              foreground: root.foreground
              fontFamily: root.fontFamily
              iconSize: Style.font.icon
              horizontalPadding: Style.space(4)
              onClicked: root.selectTab(0)
            }

            Repeater {
              model: root.accounts

              Button {
                required property var modelData
                required property int index
                width: viewSwitch.accountWidth
                height: viewSwitch.tabHeight
                text: root.displayProfileName(modelData)
                tooltipText: String(modelData.providerLabel || "AI") + " · " + text
                selected: index + 1 === root.selectedTabIndex
                bordered: true
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                horizontalPadding: Style.space(4)
                onClicked: root.selectTab(index + 1)
              }
            }
          }

          BorderSurface {
            visible: root.sleepModeActive && root.refreshOnSchedule
            width: parent.width
            implicitHeight: sleepModeRow.implicitHeight + Style.space(18)
            color: root.alpha(Color.accent, 0.10)
            borderSpec: Border.flat(root.alpha(Color.accent, 0.30), 1)
            radius: Style.cornerRadius

            Row {
              id: sleepModeRow
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(9)
              spacing: Style.space(9)

              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "󰒲"
                color: Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.icon
              }

              Column {
                width: parent.width - x
                spacing: Style.space(2)

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: "Sleep mode · OpenAI checks paused"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                }

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: "Scheduled OpenAI checks paused " + root.clockText(root.sleepStartMinute)
                    + " to " + root.clockText(root.sleepEndMinute) + " · Manual refresh still works"
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }
            }
          }

          BorderSurface {
            visible: root.summaryView
              ? root.accounts.length === 0
              : !root.account || String(root.account.error || "") !== ""
            width: parent.width
            implicitHeight: statusText.implicitHeight + Style.space(24)
            color: root.alpha(root.urgent, 0.10)
            borderSpec: Border.flat(root.alpha(root.urgent, 0.35), 1)
            radius: Style.cornerRadius

            Text {
              id: statusText
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(12)
              textFormat: Text.PlainText
              text: root.summaryView
                ? String(root.cache.error || (refreshProcess.running ? "Fetching AI usage…" : "No cached usage yet"))
                : root.account
                  ? String(root.account.error || "")
                  : String(root.cache.error || (refreshProcess.running ? "Fetching AI usage…" : "No cached usage yet"))
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }

          PanelSectionHeader {
            visible: root.summaryView && root.accounts.length > 0
            text: "USAGE LEFT"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Repeater {
            model: root.summaryView ? root.accounts : []

            BorderSurface {
              id: summaryCard
              required property var modelData
              readonly property var summaryLimit: root.preferredLimit(modelData)
              readonly property bool editingName: root.editingProfileId === root.cleanText(modelData.id, "")
              width: contentColumn.width
              implicitHeight: summaryColumn.implicitHeight + Style.space(20)
              color: root.alpha(root.foreground, 0.035)
              borderSpec: Border.flat(root.alpha(root.foreground, 0.12), 1)
              radius: Style.cornerRadius

              Column {
                id: summaryColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Style.space(10)
                spacing: Style.space(7)

                Row {
                  width: parent.width
                  spacing: Style.space(6)

                  Text {
                    visible: !summaryCard.editingName
                    width: visible ? Math.min(implicitWidth, Style.space(210)) : 0
                    textFormat: Text.PlainText
                    text: root.displayProfileName(modelData)
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    elide: Text.ElideRight
                  }

                  TextField {
                    id: profileNameField
                    visible: summaryCard.editingName
                    width: visible ? Math.min(Style.space(210), Math.max(Style.space(100),
                      parent.width - summaryPercent.width - saveProfileNameButton.width
                        - cancelProfileNameButton.width - parent.spacing * 4)) : 0
                    text: root.draftProfileName
                    placeholderText: root.defaultProfileName(modelData)
                    maximumLength: 48
                    foreground: root.foreground
                    accent: Color.accent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    onTextEdited: root.draftProfileName = text
                    onAccepted: root.saveProfileName(modelData)
                    onVisibleChanged: if (visible) Qt.callLater(function() {
                      selectAll()
                      forceActiveFocus()
                    })
                    Keys.onPressed: function(event) {
                      if (event.key === Qt.Key_Escape) {
                        root.cancelProfileNameEdit()
                        event.accepted = true
                      }
                    }
                  }

                  PanelActionButton {
                    id: editProfileNameButton
                    visible: !summaryCard.editingName && root.editingProfileId === ""
                    iconText: "󰏫"
                    tooltipText: "Rename " + root.displayProfileName(modelData)
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    size: visible ? Style.space(22) : 0
                    bordered: true
                    onClicked: root.beginProfileNameEdit(modelData)
                  }

                  PanelActionButton {
                    id: saveProfileNameButton
                    visible: summaryCard.editingName
                    iconText: "󰄬"
                    tooltipText: "Save profile name"
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    size: visible ? Style.space(22) : 0
                    bordered: true
                    onClicked: root.saveProfileName(modelData)
                  }

                  PanelActionButton {
                    id: cancelProfileNameButton
                    visible: summaryCard.editingName
                    iconText: "󰅖"
                    tooltipText: "Cancel"
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    size: visible ? Style.space(22) : 0
                    bordered: true
                    onClicked: root.cancelProfileNameEdit()
                  }

                  Item {
                    width: Math.max(0, parent.width - x - summaryPercent.width - parent.spacing)
                    height: 1
                  }

                  Text {
                    id: summaryPercent
                    textFormat: Text.PlainText
                    text: summaryLimit
                      ? Number(summaryLimit.remainingPercent || 0) + "% left"
                      : "Unavailable"
                    color: summaryLimit ? root.remainingColor(summaryLimit.remainingPercent) : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                }

                Rectangle {
                  visible: !!summaryLimit
                  width: parent.width
                  height: Style.space(7)
                  radius: height / 2
                  color: root.track

                  Rectangle {
                    width: summaryLimit
                      ? parent.width * root.clamp(Number(summaryLimit.remainingPercent || 0) / 100, 0, 1)
                      : 0
                    height: parent.height
                    radius: parent.radius
                    color: summaryLimit ? root.remainingColor(summaryLimit.remainingPercent) : root.dim
                  }
                }

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: summaryLimit
                    ? String(modelData.providerLabel || "AI") + " · " + String(summaryLimit.name || "Usage")
                      + (Number(summaryLimit.resetsAt || 0) > 0 ? " · " + root.resetText(summaryLimit.resetsAt) : "")
                    : String(modelData.error || "No usage limit available")
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }
            }
          }

          PanelSectionHeader {
            visible: !root.summaryView && !!root.account && (root.account.limits || []).length > 0
            text: "LIMITS"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Repeater {
            model: root.account ? (root.account.limits || []) : []

            BorderSurface {
              required property var modelData
              width: contentColumn.width
              implicitHeight: limitColumn.implicitHeight + Style.space(20)
              color: root.alpha(root.foreground, 0.035)
              borderSpec: Border.flat(root.alpha(root.foreground, 0.12), 1)
              radius: Style.cornerRadius

              Column {
                id: limitColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Style.space(10)
                spacing: Style.space(7)

                Row {
                  width: parent.width

                  Text {
                    textFormat: Text.PlainText
                    text: String(modelData.name || "Usage")
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }

                  Item { width: Math.max(0, parent.width - x - percentLabel.width); height: 1 }

                  Text {
                    id: percentLabel
                    textFormat: Text.PlainText
                    text: Number(modelData.remainingPercent || 0) + "% left"
                    color: root.remainingColor(modelData.remainingPercent)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                }

                Rectangle {
                  width: parent.width
                  height: Style.space(7)
                  radius: height / 2
                  color: root.track

                  Rectangle {
                    width: parent.width * root.clamp(Number(modelData.remainingPercent || 0) / 100, 0, 1)
                    height: parent.height
                    radius: parent.radius
                    color: root.remainingColor(modelData.remainingPercent)
                  }
                }

                Text {
                  visible: Number(modelData.resetsAt || 0) > 0
                  textFormat: Text.PlainText
                  text: root.resetText(modelData.resetsAt)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }
          }

          PanelSectionHeader {
            visible: !!root.account && !!root.account.credits
            text: "CREDITS"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          BorderSurface {
            visible: !!root.account && !!root.account.credits
            width: parent.width
            implicitHeight: creditsColumn.implicitHeight + Style.space(20)
            color: root.alpha(root.foreground, 0.035)
            borderSpec: Border.flat(root.alpha(root.foreground, 0.12), 1)
            radius: Style.cornerRadius

            Column {
              id: creditsColumn
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(10)
              spacing: Style.space(7)

              Row {
                width: parent.width

                Text {
                  textFormat: Text.PlainText
                  text: "Monthly credits"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                }

                Item { width: Math.max(0, parent.width - x - creditsPercent.width); height: 1 }

                Text {
                  id: creditsPercent
                  textFormat: Text.PlainText
                  text: root.account && root.account.credits
                    ? Number(root.account.credits.remainingPercent || 0) + "% left"
                    : ""
                  color: root.account && root.account.credits
                    ? root.remainingColor(root.account.credits.remainingPercent)
                    : root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                }
              }

              Rectangle {
                width: parent.width
                height: Style.space(7)
                radius: height / 2
                color: root.track

                Rectangle {
                  width: root.account && root.account.credits
                    ? parent.width * root.clamp(Number(root.account.credits.remainingPercent || 0) / 100, 0, 1)
                    : 0
                  height: parent.height
                  radius: parent.radius
                  color: root.account && root.account.credits
                    ? root.remainingColor(root.account.credits.remainingPercent)
                    : root.foreground
                }
              }

              Text {
                visible: !!root.account && !!root.account.credits
                textFormat: Text.PlainText
                text: root.account && root.account.credits
                  ? String(root.account.credits.used) + " / " + String(root.account.credits.limit)
                    + " used" + (root.account.credits.resetsAt ? " · " + root.resetText(root.account.credits.resetsAt) : "")
                  : ""
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }

          BorderSurface {
            visible: !!root.account && String(root.account.provider || "codex") === "codex"
            width: parent.width
            implicitHeight: resetRow.implicitHeight + Style.space(18)
            color: root.account && (root.account.resets || []).length > 0
              ? root.alpha(Color.accent, 0.10)
              : root.alpha(root.foreground, 0.025)
            borderSpec: Border.flat(root.alpha(root.foreground, 0.10), 1)
            radius: Style.cornerRadius

            Row {
              id: resetRow
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(9)
              spacing: Style.space(8)

              Text {
                text: root.account && (root.account.resets || []).length > 0 ? "󰑓" : "󰅖"
                color: root.account && (root.account.resets || []).length > 0 ? Color.accent : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.icon
              }

              Text {
                textFormat: Text.PlainText
                text: root.resetSummary(root.account)
                color: root.account && (root.account.resets || []).length > 0 ? root.foreground : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }

          Rectangle {
            width: parent.width
            height: 1
            color: root.alpha(root.foreground, 0.12)
          }

          Row {
            width: parent.width
            spacing: Style.space(10)

            Column {
              width: Math.max(0, parent.width - refreshButton.width - parent.spacing)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: root.lastFetchText()
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: root.sleepModeActive && root.refreshOnSchedule
                  ? "OpenAI checks paused until " + root.clockText(root.sleepEndMinute)
                  : root.refreshBehaviorText()
                color: root.dim
                opacity: 0.75
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }
            }

            Button {
              id: refreshButton
              anchors.verticalCenter: parent.verticalCenter
              text: refreshProcess.running ? "Refreshing…" : "Refresh"
              iconText: "󰑐"
              iconSpinning: refreshProcess.running
              enabled: !refreshProcess.running
              bordered: true
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.caption
              onClicked: root.refreshNow(true)
            }
          }
        }
      }
    }
  }
}
