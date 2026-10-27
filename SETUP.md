# PSX Signals: setup guide (about 20 minutes, all free)

Everything below is done in a web browser on github.com. Use a laptop for the upload step.

## 1. Create the repository
1. github.com → **New repository** → name it `psx-signals` → **Public** → Create.
2. Click **uploading an existing file**, then drag in everything from this folder: `scanner.py`, `watchlist.py`, `requirements.txt`, the `docs` folder and the `.github` folder. Commit.
3. Check that `.github/workflows/scan.yml` really is in the repo. Hidden folders sometimes get skipped. If it is missing: **Add file → Create new file**, type `.github/workflows/scan.yml` as the name, and paste the contents.

## 2. Add your private settings
Repo → **Settings → Secrets and variables → Actions**.

**Secrets** tab → New repository secret (add each):
| Name | Value |
|---|---|
| `DASH_PASSWORD` | your dashboard password (14+ characters, never share it) |
| `NTFY_TOPIC` | a long random name, e.g. `psx-k8x92mq4vz7r` |
| `EMAIL_USER` | your Gmail address |
| `EMAIL_APP_PASSWORD` | Gmail app password (Google Account → Security → 2-Step Verification → App passwords) |
| `EMAIL_TO` | where alerts go (can be the same Gmail) |

**Variables** tab → New repository variable:
| Name | Value |
|---|---|
| `CAPITAL` | your trading capital in PKR (plain number) |
| `RISK_PCT` | `2` |

## 3. Turn on the dashboard
Repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch `main`, folder `/docs` → Save.
Your dashboard will be at `https://YOUR-USERNAME.github.io/psx-signals/` (appears in a minute or two).

## 4. Connect your phone
In the ntfy app tap **+** → subscribe to the exact topic name you used in `NTFY_TOPIC`.
Also: GitHub → Settings → Emails → tick **Keep my email addresses private**.

## 5. Test it
Repo → **Actions → scan → Run workflow** → tick **force** → Run.
- Green tick and a new `docs/signals.enc.json` file: it works. Open the dashboard and enter your password.
- Red cross: open the run, then the "Scan" step, and send me the error text (hide any secrets).
- A "data problem" message in the dashboard or a ntfy alert means the PSX data feed did not respond. Send me the text and I will adapt the scanner.

After that it runs by itself every 5 minutes during market hours, Mon to Fri.

## Things to know
- **PSX data endpoints are unverified.** I could not reach them from my environment, so step 5 is the real test.
- **Market hours** are set in `scanner.py` (`market_open`, `signal_window`). Check them against PSX.
- **Shariah tags** use an approximate list in `watchlist.py`. Verify against the current KMI list.
- Signals only fire between 09:45 and 14:15, at most 3 a day, at least 30 minutes apart, and none if nothing scores well. A quiet day with no signal is normal.
- Position size uses `RISK_PCT` of capital per trade, capped at 35% of capital in one stock. Brokerage, CGT and slippage are not included.
- First 2 to 4 weeks: paper trade. Write down every signal and what happened before using real money.
- Not financial advice. Signals can be wrong and stop losses can gap.
