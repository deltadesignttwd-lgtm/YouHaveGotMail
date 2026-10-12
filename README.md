# YouHaveGotMail

A daily briefing bot. Every morning at **08:00 London time** it reads the RSS feeds in
`briefing.py`, sends any new items to you on **Telegram**, and adds them as rows in a **Google Sheet**.
Items already in the sheet are never sent twice.

Runs free on GitHub Actions (`.github/workflows/briefing.yml`), so no server is needed.

## One-time setup

1. **Telegram bot**
   - Message [@BotFather](https://t.me/BotFather), send `/newbot`, copy the **bot token**.
   - Send your new bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates`
     and copy the number in `"chat":{"id": ...}`. That's your **chat ID**.
2. **Google Sheet**
   - In [Google Cloud Console](https://console.cloud.google.com), create a project and enable the **Google Sheets API**.
   - IAM & Admin → Service Accounts → create one → Keys → Add key → **JSON**, then download it.
   - Create a blank Google Sheet, click **Share**, and add the service account's email
     (`…@….iam.gserviceaccount.com`) as **Editor**. Headers are added automatically.
   - Copy the **sheet ID** from the URL: `docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.
3. **GitHub secrets**: repo → Settings → Secrets and variables → Actions → *New repository secret*:

   | Name           | Value                                   |
   |----------------|-----------------------------------------|
   | `TG_TOKEN`     | Telegram bot token                      |
   | `TG_CHAT_ID`   | Your chat ID                            |
   | `SHEET_ID`     | Google Sheet ID                         |
   | `GOOGLE_CREDS` | Entire contents of the JSON key file    |

4. **Test**: Actions tab → *Daily Briefing* → **Run workflow**. Manual runs always send immediately.
   The workflow must be on the default branch for the daily schedule to run.

## Customising

- **Feeds**: edit the `FEEDS` list in `briefing.py`.
- **How far back**: `MAX_AGE_DAYS` in `briefing.py` (default 7). Older articles are never sent.
- **Time**: change `SEND_HOUR` in `briefing.py` *and* the two cron lines in the workflow
  (they are the UTC hours that equal your London hour in summer and in winter).

## Notes

- GitHub scheduled runs can start a few minutes to ~30 min late.
- GitHub disables schedules after 60 days without repo activity; re-enable from the Actions tab.
