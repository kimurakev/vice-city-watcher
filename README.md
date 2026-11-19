# Vice City drop watcher

Checks the Heat Store, the Heat uniform page, Nike / SNKRS, Fanatics, NBA Store, the Travis Scott shop and the main Resell Calendar and Sole Retriever articles every 5 minutes, and pushes a notification to your phone the moment any of them change (new Cactus Jack product, a price, a stock flip, an edited article).

Nothing to install locally. It runs on GitHub Actions for free.

## Setup (about 10 minutes)

### 1. Phone notifications (ntfy)

1. Install the free **ntfy** app (iOS App Store or Google Play).
2. Tap **+** and subscribe to a topic. Pick something private and hard to guess, for example `kb-vicecity-7q3x9`. Anyone who knows the topic name can read it, so do not use `heat` or `vicecity`.
3. Remember that topic name. You will paste it into GitHub in step 3.

### 2. Create the repo

1. On GitHub, click **New repository**. Name it anything (`vice-city-watcher`).
   Public is recommended: Actions minutes are unlimited on public repos. A private repo gets 2,000 free minutes a month, which is enough for roughly a week at 5-minute checks.
2. Upload these files, keeping the folder structure:
   - `watch.py`
   - `README.md`
   - `.github/workflows/watch.yml`

   Easiest way: on the empty repo page click **uploading an existing file**, drag the three files in (GitHub keeps the `.github/workflows` path if you drag the folder), and commit.

### 3. Add the secret

Repo **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
Name: `NTFY_TOPIC`. Value: the topic name from step 1. Save.

### 4. Turn it on

1. Open the **Actions** tab. If GitHub asks you to enable workflows, click the green button.
2. Click **Vice City watcher** in the left list, then **Run workflow** > **Run workflow** to do the first check by hand.
3. Within a minute you should get a push: "Vice City watcher is live". That first run only records what the pages look like now. Every run after that alerts on differences.

From then on it runs itself every 5 minutes. GitHub's scheduler sometimes lags a few minutes at busy times.

## What a notification looks like

```
CHANGE: Heat Store products (Cactus Jack / Vice City)
NEW:
+ Nike x Cactus Jack Vice City Swingman Jersey | $150.00 | 12/12 variants in stock | /products/...
```

Tapping the notification opens the page.

## Tweaks

- **Add or remove pages**: edit the `WATCHES` list at the top of `watch.py`. Three types: `shopify` (any Shopify store, reads its product feed, catches new products, prices and stock), `keywords` (any page, keeps only lines that mention Cactus Jack / Vice City / GTA), `fulltext` (any page, alerts on any edit).
- **Change the keywords**: edit `KEYWORDS` in `watch.py`.
- **Change how often it runs**: edit the cron line in `.github/workflows/watch.yml`. `*/5` is every 5 minutes (GitHub's minimum), `*/30` every 30, `0 * * * *` hourly.
- **Pause it**: Actions tab > Vice City watcher > the "..." menu > Disable workflow.
- **Reset the baseline**: delete `state.json` from the repo and run the workflow by hand.

## Notes

- Some sites (Fanatics, NBA Store, sometimes Nike) block automated requests. If one does, you get a single low-priority "can't read" notice and the watcher stays quiet about it until it becomes readable again. The Heat Store and Travis Scott shop use the Shopify product feed, which is the most reliable signal for a new product or price.
- The watcher only fetches pages, it does not buy anything or log in anywhere.
- GitHub disables scheduled workflows on repos with no commits for 60 days. The watcher commits `state.json` whenever something changes, which keeps it alive.
