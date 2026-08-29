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

The deploy workflow fires only on a completed Build run on this repo's
`master` (or a manual dispatch by someone with write access) — never from
a fork or PR. Belt and braces, in **Settings → Actions → General** also
set:

- *Fork pull request workflows*: **Require approval for all outside
  collaborators**.

Keep the container single-purpose: nothing else should run in it, and it
holds no credentials beyond the runner token.

## 4. Use it

Nothing to trigger: every push to `master` whose Build workflow goes
green deploys automatically. Each deploy installs the latest rolling
release, smoke-tests the live site, does the one-off data downloads if
the files are missing (postcodes ~25 MB, GB map tiles ~2–3 GB — expect a
long first deploy), and runs a bounded verification scrape (5 pages per
source) against the real National Trust / English Heritage sites, with a
result summary in the run log. A manual run from the Actions tab accepts
a `scrape_max_pages` input (`0` skips the scrape). Run the full scrape
with `systemctl start daysout-scrape` in the container (or wait for the
daily 05:30 timer).
