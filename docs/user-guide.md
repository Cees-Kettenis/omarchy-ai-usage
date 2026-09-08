# AI Usage user guide

AI Usage shows the usage remaining across your local OpenAI Codex and Claude
Code profiles. Click its bar icon to open the summary. The plugin uses your
signed-in CLI profiles; you do not paste credentials into the widget.

## Set up your profiles

Install the plugin using the [README instructions](../README.md#install), then
open its popup and click the gear after the account tabs.

<p align="center">
  <img src="screenshots/settings.png" width="396" alt="Settings with OpenAI profile location, refresh controls, Claude account setup, capture buttons, and privacy">
</p>

1. Under **OpenAI**, choose a Codex home or a parent folder containing separate
   Codex homes. Each signed-in profile has an `auth.json` file. The default
   parent location is `~/.codex-profiles`.
2. Under **Claude**, choose **Single account** for one Claude config home,
   normally `~/.claude`. Choose **Multiple accounts** for a parent folder whose
   immediate children are separate signed-in `CLAUDE_CONFIG_DIR` homes.
3. Use the folder buttons or type an absolute path or a path beginning with
   `~/`. The popup hides while the picker is open, then returns with your
   selection and other unsaved changes. Cancelling keeps the previous path.
4. Scroll down and click **Save**. **Cancel** discards your settings edits.

The locations in the screenshot are examples. Select your own profile folders.
Single-account Claude mode checks one home; multiple-account mode checks the
immediate children of the selected parent, without searching deeper folders.

## Enable Claude usage capture

Save your Claude location first, then click **Enable Claude Code usage capture**.
Check the result below the buttons. Send a message in each configured Claude
Code profile, then refresh the widget to load the captured usage.

Capture adds a local command to each discovered profile's `settings.json`.
Claude Code runs it through its status-line interface to record usage. It also
shows a compact usage line in Claude Code. Enabling capture does not send a
model request, and routine widget refreshes never install capture.

If you already use a custom Claude status line, setup leaves it alone and
reports that capture could not be installed for that profile. That profile
will not receive new usage through AI Usage until the conflict is resolved.
Repeat setup after adding another profile.

## Read the summary and account views

<p align="center">
  <img src="screenshots/summary.png" width="405" alt="Summary with GPT 1 through GPT 4 and Claude 1, each showing usage remaining and reset time">
</p>

Each summary card shows a profile name, percentage remaining, usage bar, and
reset time. The summary prefers the five-hour limit and uses the weekly limit
when a five-hour window is unavailable. **0% left** means that window is
exhausted; it is not the percentage used.

Click an account tab for its available limits and reset information. Click
the chart tab at the left to return to the summary.

<p align="center">
  <img src="screenshots/details.png" width="407" alt="GPT 1 detail view showing five-hour and weekly usage remaining, reset times, and available resets">
</p>

The footer shows the last fetch time. Claude usage changes when Claude Code
emits a new usage snapshot after a message. Refreshing the widget reads that
snapshot and checks sign-in state; it does not ask Claude to generate a message.

## Name your accounts

Click the pencil beside a summary name, enter a name, then click the checkmark
or press Enter. The same name appears in the summary and account tabs.
Click the cancel icon or press Escape to abandon the edit.

Clear the name and save to restore its default. Names are display labels only;
they do not rename folders or change credentials. The examples in the
screenshots use custom names such as **GPT 1** and **Claude 1**.

## Refresh, sleep, and privacy

OpenAI refresh defaults to **Scheduled**, every 15 minutes. Choose **On
hover/open** to fetch when hovering over the bar icon or opening the popup,
or **Both** to combine the triggers. The hover cooldown defaults to 60 seconds.

**Pause scheduled checks** enables a daily sleep window. It pauses scheduled
OpenAI checks only. Manual refresh and hover/open refresh still work, and the
last cached result remains visible.

**Hide account details** is on by default. It hides account email and
subscription details and keeps them out of new private fetches. Profile names
remain visible, so choose names you are comfortable showing in screenshots.

Useful controls while viewing usage:

- Click **Refresh**, or right-click or middle-click the bar icon, to refresh.
- Press `r` or Enter to refresh from the popup.
- Use the arrow keys, or `h` and `l`, to move between account tabs.
- Press Escape to close the popup.

## Remove capture and uninstall

Before uninstalling AI Usage, open settings and click **Remove Claude Code
usage capture**. Wait for the result below the buttons.

Removal clears only the matching AI Usage status-line command in profiles at
the saved Claude location. It preserves other settings and leaves a different
custom status line alone. Removing capture again is safe if it is already
absent. If you previously enabled capture at another location, select and save
that location and repeat removal there before uninstalling.

Then run:

```bash
omarchy plugin remove ai-usage
```

The uninstall command does not remove capture for you. Skipping the capture
removal step leaves Claude settings pointing at the removed plugin. Merely
disabling the widget also leaves capture installed.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| No accounts appear | Save the correct provider locations and sign in using the corresponding CLI. The collector ignores symlinks, unsafe permissions, and folders containing both provider credential markers. |
| Claude usage is missing | Save the Claude location, enable capture, read the setup result, and send a Claude Code message in that profile. Refresh the widget afterward. |
| Setup reports an existing custom status line | Capture was not installed for that profile. AI Usage does not replace your custom command. |
| A folder selection has not taken effect | After returning from the picker, scroll down and click **Save**. |
| Changes to local plugin code do not appear | Run `omarchy restart shell` to load the current files if a plugin rescan reused cached QML. |

For command-line options, multiple-account examples, cache behavior, and
provider details, see [How it works](how-it-works.md). For data handling, see
[Security and privacy](../SECURITY.md).
