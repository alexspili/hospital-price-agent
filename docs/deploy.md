# Deploying the hosted demo

The demo is one container holding one DuckDB file on a mounted disk, with Caddy in front
of it for HTTPS. The pre-scanned Houston ZIPs answer instantly from that file; a live scan
is opt-in, needs the shared PIN, and is bounded by the caps below.

Target: a small ARM VM on AWS (Lightsail 2 GB, or EC2 `t4g.small`) with a 20 GB disk and
a domain you control. About $13 a month, less if your account still has free tier.

## Before you start

- A domain you can add a DNS record to.
- The compact database, made on your machine from the working one:

  ```bash
  hpa export-demo --out data/demo.duckdb        # the pre-scanned ZIPs only
  ```

  It carries the reference tables whole (so any ZIP still resolves to its nearest five),
  the discovery results and extracted rows for the pre-scanned hospitals, and the model
  cache, so the host never pays again for an answer you already have.
- A PIN you are willing to share with the people you want to let scan live.

## 1. The machine

Lightsail: create an instance, Linux/Unix, OS-only Debian 12, ARM, the 2 GB plan; attach a
20 GB block storage disk. EC2: `t4g.small`, Debian 13 ARM, a 20 GB gp3 volume, security
group open on 22, 80 and 443.

Two gigabytes of memory is the point: extracting the largest Houston file peaks around
470 MB, and the 1 GB plans leave no room for the OS underneath that.

## 2. The disk

```bash
lsblk                                   # find the attached device, e.g. /dev/nvme1n1
sudo mkfs.ext4 /dev/nvme1n1             # ONLY if it is a fresh, empty disk
sudo mkdir -p /mnt/hpa
echo '/dev/nvme1n1 /mnt/hpa ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a && sudo chown -R $USER /mnt/hpa
```

The database lives here rather than in the container, so `docker compose up --build` never
costs you the scanned data.

## 3. Docker

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

## 4. DNS

Point an A record at the instance's static IP:

```
demo.yourdomain.com.   A   <the static IP>
```

Caddy asks Let's Encrypt for the certificate on first boot, which only works once this
record resolves. Check it with `dig +short demo.yourdomain.com` before continuing.

## 5. The code, the data and the settings

```bash
git clone https://github.com/alexspili/hospital-price-agent.git ~/hpa && cd ~/hpa
cp deploy/env.example .env && $EDITOR .env      # domain, PIN, caps, API key
```

From your own machine, copy the database onto the disk:

```bash
scp data/demo.duckdb admin@<ip>:/mnt/hpa/hpa.duckdb
```

## 6. Up

```bash
docker compose up -d --build
docker compose logs -f hpa          # "live scans: PIN required, 4/hour per address, ..."
```

Then check it from outside:

```bash
curl -s https://demo.yourdomain.com/api/health
curl -s https://demo.yourdomain.com/api/config      # live_needs_pin: true
```

Open the page: it lands on the recorded run, and a search of a pre-scanned ZIP answers
from the file with no network. Tick **run live**, enter the PIN, and watch the trace.

## What is enforced, and where

| Limit | Set by | What happens |
|---|---|---|
| Live scans need the PIN | `HPA_LIVE_PIN` | 403 with a plain message; pre-scanned answers are unaffected |
| Live runs per IP per hour | `HPA_RUNS_PER_HOUR` | 429 with `Retry-After`; counted in memory, forgotten on restart |
| Files downloaded per run | `HPA_MAX_DOWNLOADS` | Hospitals past the cap are reported as capped, not dropped |
| Model spend per day | `HPA_DAILY_CAP_USD` | Claude stops being called; the deterministic pipeline carries on |
| Two runs at a time | built in | The third gets "busy, try again" |
| Disk | `HPA_KEEP_DOWNLOADS=0` | The raw price file is deleted once its rows are in DuckDB |

`HPA_TRUST_PROXY=1` tells the server the client address is Caddy's `X-Forwarded-For`
rather than the socket, which is what makes the per-IP limit mean anything behind a proxy.
Set it only when something trustworthy is in front.

## Operating it

```bash
docker compose logs -f hpa                  # the trace of every run, as it happens
docker compose up -d --build                # deploy a new commit (git pull first)
docker compose down                         # stop; the database stays on /mnt/hpa
```

What the model has cost, straight from the ledger the server writes:

```bash
docker compose exec hpa python -c "
from hpa import store, llm
con = store.connect('/data/hpa.duckdb', read_only=True)
print(f'today: \${llm.spend_today(con):.2f}')
print(con.execute('SELECT fn, count(*), round(sum(usd), 4) FROM llm_spend GROUP BY 1').fetchall())"
```

Back it up by copying the file off; nothing else on the disk matters:

```bash
scp admin@<ip>:/mnt/hpa/hpa.duckdb ./backup-$(date +%F).duckdb
```

To rotate the PIN, change it in `.env` and `docker compose up -d` — no rebuild needed.

## When something is wrong

- **The certificate never arrives.** `docker compose logs caddy`. Almost always DNS: the A
  record has to resolve before Caddy can prove the domain is yours.
- **The trace arrives all at once at the end.** Something is buffering the event stream.
  Caddy is configured with `flush_interval -1` for exactly this; check nothing else (a CDN,
  another proxy) is in the path.
- **A live scan is killed part-way.** Almost certainly memory: check `docker compose logs`
  for an OOM kill, and remember the 1 GB plans cannot extract the largest files.
- **The disk fills.** `HPA_KEEP_DOWNLOADS=0` should prevent it; if it happens anyway, look
  for leftovers in `/mnt/hpa/mrf/` from an interrupted scan.
- **The CLI says the server owns the database.** It does, by design: stop the container, or
  read through the API (SPEC "Process model").
