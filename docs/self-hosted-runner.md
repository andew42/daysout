# Self-hosted runner: deploy and test on the house server

One-time setup that lets the **Deploy to house server** workflow
(`.github/workflows/deploy.yml`) install and test every build directly in
an LXD container on the house server. After this, a development session
can push, trigger the deploy, and read the results from the runner logs —
no manual steps — while the site stays visible on the LAN at
`http://<container-ip>:8080`.

## 1. Create the container

On the house server:

```bash
lxc launch ubuntu:24.04 daysout
lxc exec daysout -- bash
```

(Any systemd distro works; the rest assumes you're inside the container.)

## 2. Register the runner

GitHub → `daysout` repo → **Settings → Actions → Runners → New
self-hosted runner → Linux x64**, then run the commands GitHub shows you.
Inside a dedicated, disposable container it's fine to run as root:

```bash
apt-get update && apt-get install -y curl python3 sudo
mkdir /root/actions-runner && cd /root/actions-runner
# ... the curl + tar commands from the GitHub page ...
export RUNNER_ALLOW_RUNASROOT=1
./config.sh --url https://github.com/andew42/daysout --token <TOKEN-FROM-PAGE>
./svc.sh install root && ./svc.sh start
```

The runner should appear as **Idle** on the Runners page.

## 3. Security settings (public repo + self-hosted runner)

The deploy workflow is `workflow_dispatch`-only, so it can only be
triggered by someone with write access — never by a fork or PR. Belt and
braces, in **Settings → Actions → General** also set:

- *Fork pull request workflows*: **Require approval for all outside
  collaborators**.

Keep the container single-purpose: nothing else should run in it, and it
holds no credentials beyond the runner token.

## 4. Use it

Trigger **Actions → Deploy to house server → Run workflow** (or let a
Claude session trigger it via the API). Inputs:

- `import_postcodes` (default on): one-off ~25 MB Code-Point Open import
  when the table is empty.
- `download_tiles` (default off): one-off ~2–3 GB GB map tile download.
  Turn it on once; later runs skip it because the file exists.
- `scrape_max_pages` (default 5): bounded verification scrape of the real
  National Trust / English Heritage sites; `0` skips it. The result
  summary step prints what was scraped. Run the full scrape with
  `systemctl start daysout-scrape` in the container (or wait for the
  daily 05:30 timer).

Each run installs the **latest rolling release**, so push → wait for the
Build workflow (~90 s) → dispatch deploy.
