# Deploying the hosted demo

The demo is one container holding one DuckDB file on a mounted disk, with Caddy in front
of it for HTTPS. The pre-scanned Houston ZIPs answer instantly from that file; a live scan
is opt-in, needs the shared password, and is bounded by the caps below.

Target: a small ARM VM on AWS and a domain you control. Two routes below — Lightsail,
whose plans include their own disk, or EC2 with a volume attached. Roughly $10-15 a month
either way; check the current price in the console rather than trusting this line.

You do not need web hosting. The instance is the host; the domain needs one A record.

## Before you start

- A domain you can add a DNS record to.
- The compact database, made on your machine from the working one:

  ```bash
  hpa export-demo --out data/demo.duckdb        # the pre-scanned ZIPs only
  ```

  It carries the reference tables whole (so any ZIP still resolves to its nearest five),
  the discovery results and extracted rows for the pre-scanned hospitals, and the model
  cache, so the host never pays again for an answer you already have.
- A password you are willing to share with the people you want to let scan live (one word; case does not matter).

## 1. The machine

**Lightsail (simpler).** Create an instance: Linux/Unix, OS-only **Debian**, **ARM**, the
**2 GB** plan. Its plan includes an SSD, so there is no separate volume to attach or
format. Then attach a **static IP** (free while it is attached to a running instance) —
the automatic IP changes on stop/start and would break DNS. Ports 80 and 443 are open by
default in Lightsail's firewall; check that they are.

**EC2 (more control).** A `t4g.small` with Debian ARM, a 20 GB gp3 volume, an Elastic IP,
and a security group open on 22, 80 and 443.

Two gigabytes of memory is the point: extracting the largest Houston file peaks around
470 MB, and the 1 GB plans leave no room for the OS underneath that.

## 2. Where the database lives

On Lightsail the instance disk is enough:

```bash
sudo mkdir -p /mnt/hpa && sudo chown -R $USER /mnt/hpa
```

On EC2, format and mount the separate volume there instead:

```bash
lsblk                                   # find the attached device, e.g. /dev/nvme1n1
sudo mkfs.ext4 /dev/nvme1n1             # ONLY if it is a fresh, empty disk
sudo mkdir -p /mnt/hpa
echo '/dev/nvme1n1 /mnt/hpa ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a && sudo chown -R $USER /mnt/hpa
```

Either way the database sits outside the container, so `docker compose up --build` never
costs you the scanned data.

## 3. Docker

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

## 4. DNS

One A record at the registrar, pointing the subdomain at the instance's static IP. At
Porkbun that is Domain Management -> DNS -> Add record:

| Type | Host | Answer | TTL |
|---|---|---|---|
| A | `prices` | the static IP | 600 |

Nothing else: no web hosting, no nameserver change, no certificate to buy.

Caddy asks Let's Encrypt for the certificate on first boot, which only works once this
record resolves — check before continuing, and give it a few minutes if it does not:

```bash
dig +short prices.alexspi.com          # should print the static IP
```

## 5. The code, the data and the settings

```bash
git clone https://github.com/alexspili/hospital-price-agent.git ~/hpa && cd ~/hpa
cp deploy/env.example .env && $EDITOR .env      # domain, password, caps, API key
```

From your own machine, copy the database onto the disk (214 MB, a few minutes):

```bash
hpa export-demo --out data/demo.duckdb
scp data/demo.duckdb admin@<static-ip>:/mnt/hpa/hpa.duckdb
```

The API key is optional. Without it the deterministic pipeline still runs; the three
fallbacks (website search, index tie-break, service confirmation) are simply skipped, and
the answers already bought travel in the copy's model cache.

## 6. Up

```bash
docker compose up -d --build
docker compose logs -f hpa          # "live scans: password required, 4/hour per address, ..."
```

Then check it from outside:

```bash
curl -s https://prices.alexspi.com/api/health
curl -s https://prices.alexspi.com/api/config      # live_needs_pin: true
```

Open the page: it lands on the recorded run, and a search of a pre-scanned ZIP answers
from the file with no network. Tick **run live**, enter the password, and watch the trace.

## What is enforced, and where

| Limit | Set by | What happens |
|---|---|---|
| Live scans need the password | `HPA_LIVE_PIN` | 403 with a plain message; pre-scanned answers are unaffected |
| Live runs per IP per hour | `HPA_RUNS_PER_HOUR` | 429 with `Retry-After`; counted in memory, forgotten on restart |
| Files downloaded per run | `HPA_MAX_DOWNLOADS` | Hospitals past the cap are reported as capped, not dropped |
| Model spend per day | `HPA_DAILY_CAP_USD` | Claude stops being called; the deterministic pipeline carries on. A soft limit: it is checked before each call against what has been recorded, so concurrent runs can overshoot it by a call or two (a few cents) |
| Two runs at a time | built in | The third gets "busy, try again" |
| Disk | `HPA_KEEP_DOWNLOADS=0` | The raw price file is deleted after extraction, whether it succeeded or not; a partial download is removed on failure |
| A password is mandatory | `HPA_REQUIRE_PIN=1` (set in `docker-compose.yml`) | The server refuses to start with an empty `HPA_LIVE_PIN`, rather than serving live scans to anyone |

`HPA_TRUST_PROXY=1` tells the server the client address is Caddy's `X-Forwarded-For`
rather than the socket, which is what makes the per-IP limit mean anything behind a proxy.
Set it only when something trustworthy is in front.

## Operating it

```bash
docker compose logs -f hpa                  # the trace of every run, as it happens
docker compose up -d --build                # deploy a new commit (git pull first)
docker compose down                         # stop; the database stays on /mnt/hpa
```

What the model has cost: the server prints the running total after every live run, so it
is in the process log. Nothing else can read the ledger while the server is up — it holds
the database, and DuckDB gives the file to one process at a time (SPEC "Process model"):

```bash
docker compose logs hpa | grep '\[spend\]' | tail -5
```

To query the ledger itself, stop the server first, or copy the file off and open the copy:

```bash
docker compose stop hpa
docker compose run --rm hpa python -c "
from hpa import store, llm
con = store.connect('/data/hpa.duckdb', read_only=True)
print(f'today: \${llm.spend_today(con):.2f}')
print(con.execute('SELECT fn, count(*), round(sum(usd), 4) FROM llm_spend GROUP BY 1').fetchall())"
docker compose start hpa
```

Back it up with the server stopped: while it runs, DuckDB keeps a write-ahead log
(`hpa.duckdb.wal`) beside the file, and a copy of the `.duckdb` alone can be missing
recent rows or fail to open.

```bash
docker compose stop hpa
scp admin@<ip>:/mnt/hpa/hpa.duckdb ./backup-$(date +%F).duckdb
docker compose start hpa
```

Nothing else on the disk needs backing up: `/mnt/hpa/mrf/` holds price files a scan may
reuse, and `HPA_KEEP_DOWNLOADS=0` keeps it empty.

To change the password, edit `HPA_LIVE_PIN` in `.env` and `docker compose up -d` — no rebuild needed.

## When something is wrong

- **The certificate never arrives.** `docker compose logs caddy`. Almost always DNS: the A
  record has to resolve before Caddy can prove the domain is yours.
- **The trace arrives all at once at the end.** Something is buffering the event stream.
  Caddy is configured with `flush_interval -1` for exactly this; check nothing else (a CDN,
  another proxy) is in the path.
- **A live scan is killed part-way.** Almost certainly memory: check `docker compose logs`
  for an OOM kill, and remember the 1 GB plans cannot extract the largest files.
- **The disk fills.** `HPA_KEEP_DOWNLOADS=0` should prevent it; if it happens anyway, look
  for leftovers in `/mnt/hpa/mrf/` (the container's `/data/mrf`) from a scan that was
  killed outright, and delete any `download.*.part`.
- **The CLI says the server owns the database.** It does, by design: stop the container, or
  read through the API (SPEC "Process model").
