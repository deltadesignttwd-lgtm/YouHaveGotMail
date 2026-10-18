# YouHaveGotMail

A daily briefing bot. Every morning at **08:00 London time** it reads the RSS feeds listed in
the **Feeds** tab of your Google Sheet and sends you **one file on Telegram**: a reading page
(`briefing-YYYY-MM-DD.html`) with the full text of every new article, extracted with
[trafilatura](https://trafilatura.readthedocs.io/). Tap the file to open it in your browser.

- Paywalled or blocked pages fall back to the feed's summary; podcast episodes show their show notes.
- Problems (a broken feed link, a cell that isn't a link) appear as notices at the top of the page.
- On days with nothing new, the file still arrives and says "No new items today".
- Each item is recorded as a row in the Google Sheet once the file is delivered, and is never sent twice.
- The page goes privately to your chat and is never published.

Runs free on GitHub Actions (`.github/workflows/briefing.yml`), so no server is needed.
The daily start is triggered by a free [cron-job.org](https://cron-job.org) job (see below).

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

## Customising

- **Feeds**: edit the **Feeds** tab of your Google Sheet. No code changes needed.
  The bot creates this tab on its first run. Columns:

  | url | name | on |
  |---|---|---|
  | the RSS link | optional label shown in Telegram | `yes` / blank = on, `no` = paused |

  Add a row to follow a feed, set `on` to `no` to pause it, delete the row to remove it.
  Changes apply on the next run. Your record of sent items stays in the first tab.
- **How many**: at most 20 items a day (`MAX_PER_DAY` in `briefing.py`), at most 10 per feed.
  Feeds take turns, newest first, so one busy feed can't crowd out the others.
  Items over the limit aren't recorded and can still appear on a later day.
- **How far back**: `MAX_AGE_DAYS` in `briefing.py` (default 14). Older articles are never sent.
- **Time**: edit the job's schedule in cron-job.org. No code change needed.

## Notes

## Daily trigger (cron-job.org)

GitHub's built-in schedule is not used. A cron-job.org job calls GitHub every day at
08:00 (time zone Europe/London):

- **URL**: `https://api.github.com/repos/deltadesignttwd-lgtm/YouHaveGotMail/actions/workflows/briefing.yml/dispatches`
- **Method**: `POST`, **body**: `{"ref":"main"}`
- **Headers**: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
  `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`
- **Token**: a fine-grained GitHub token limited to this repo with *Actions: Read and write*.
  When it expires, create a new one and paste it into the job's Authorization header.

A successful call returns status **204** and appears in the Actions tab as "Manually run".
