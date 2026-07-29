# Hosting an APT repository on GitHub (free)

This guide shows you how to turn a regular GitHub repository into a valid APT
repository that `install.sh` and axupdate can consume.

---

## How it works

GitHub Pages serves static files over HTTPS from your repository.  
APT only needs static files (a `Packages` index + signed `Release` file +  
the `.deb` packages themselves), so GitHub Pages is a perfect free host.

```
https://YourUser.github.io/axpm-repo/          ← APT repo root (URIs in .sources)
https://YourUser.github.io/axpm-repo/dists/stable/Release
https://YourUser.github.io/axpm-repo/dists/stable/main/binary-amd64/Packages.gz
https://YourUser.github.io/axpm-repo/pool/main/axpm_1.0_amd64.deb
```

---

## Step 1 — Create the GitHub repository

1. Create a new **public** repo on GitHub, e.g. `axpm-repo`.
2. Enable **GitHub Pages**:  
   Settings → Pages → Source: **Deploy from a branch** → Branch: `main` / `(root)`
3. Wait ~1 minute. Your site will be live at `https://YourUser.github.io/axpm-repo`.

---

## Step 2 — Generate a GPG signing key (do this once)

```bash
# Generate a dedicated signing key — do NOT use your personal key
gpg --batch --gen-key <<EOF
%no-protection
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: axpm Repo
Name-Email: axpm@yourdomain.org
Expire-Date: 0
EOF

# Get the key fingerprint
gpg --list-keys axpm@yourdomain.org

# Export the PUBLIC key as binary .gpg (what install.sh downloads)
gpg --export axpm@yourdomain.org > axpm.gpg

# Export armored .asc (optional — human-readable, also works with install.sh)
gpg --armor --export axpm@yourdomain.org > axpm.asc

# Keep the PRIVATE key safe — you need it to sign each repo update
# Export private key backup:
gpg --armor --export-secret-keys axpm@yourdomain.org > axpm-private.asc
# Store axpm-private.asc somewhere SAFE and OFFLINE — never commit it to git
```

---

## Step 3 — Build the repository directory structure

Run this script in a local working directory (not inside your .deb source tree):

```bash
#!/usr/bin/env bash
# build-repo.sh — run this each time you add or update a .deb package
set -euo pipefail

REPO_DIR="./axpm-repo"          # local copy of your GitHub Pages repo
POOL_DIR="${REPO_DIR}/pool/main"
DISTS_DIR="${REPO_DIR}/dists/stable"
BINARY_DIR="${DISTS_DIR}/main/binary-amd64"
GPG_KEY_EMAIL="axpm@yourdomain.org"   # matches the key you generated above

mkdir -p "${POOL_DIR}" "${BINARY_DIR}"

# ── Copy your .deb files into pool/ ─────────────────────────────────────────
# Place all your .deb packages into ${POOL_DIR} before running this script.
# Example:  cp axpm_1.0_amd64.deb "${POOL_DIR}/"

# ── Generate Packages index ──────────────────────────────────────────────────
(cd "${REPO_DIR}" && dpkg-scanpackages pool/main) > "${BINARY_DIR}/Packages"
gzip  -9 -k -f "${BINARY_DIR}/Packages"     # → Packages.gz
bzip2 -9 -k -f "${BINARY_DIR}/Packages"     # → Packages.bz2  (optional)

# ── Generate Release file ────────────────────────────────────────────────────
cat > "${DISTS_DIR}/Release" <<EOF
Origin: axpm
Label: axpm
Suite: stable
Codename: stable
Date: $(date -Ru)
Architectures: amd64 arm64
Components: main
Description: axpm package repository
EOF

# Append SHA256 checksums of all index files
echo "SHA256:" >> "${DISTS_DIR}/Release"
(cd "${DISTS_DIR}" && find main/ -type f | sort | while read -r f; do
    echo " $(sha256sum "$f" | cut -d' ' -f1) $(wc -c < "$f") $f"
done) >> "${DISTS_DIR}/Release"

# ── Sign the Release file ────────────────────────────────────────────────────
# Detached signature (Release.gpg)
gpg --batch --yes --default-key "${GPG_KEY_EMAIL}" \
    --armor --detach-sign \
    --output "${DISTS_DIR}/Release.gpg" \
    "${DISTS_DIR}/Release"

# Inline signature (InRelease — preferred by modern apt)
gpg --batch --yes --default-key "${GPG_KEY_EMAIL}" \
    --armor --clearsign \
    --output "${DISTS_DIR}/InRelease" \
    "${DISTS_DIR}/Release"

# ── Copy public GPG key to repo root ────────────────────────────────────────
cp axpm.gpg "${REPO_DIR}/axpm.gpg"
cp axpm.asc "${REPO_DIR}/axpm.asc"   # optional armored copy

echo "Repository built successfully at ${REPO_DIR}/"
echo "Commit and push ${REPO_DIR}/ to your GitHub Pages repo."
```

Make it executable and run it:

```bash
chmod +x build-repo.sh

# Drop your .deb files into axpm-repo/pool/main/ first, then:
./build-repo.sh
```

---

## Step 4 — Push to GitHub

```bash
cd axpm-repo
git init                          # only needed the first time
git remote add origin https://github.com/YourUser/axpm-repo.git
git add .
git commit -m "repo: update packages"
git push origin main
```

GitHub Pages will publish the new files within ~60 seconds.

---

## Step 5 — Configure install.sh

Open `sources/install.sh` and set exactly these three lines:

```bash
AXPM_REPO_URI="https://YourUser.github.io/axpm-repo"
AXPM_REPO_SUITE="stable"
AXPM_KEY_URL="https://raw.githubusercontent.com/YourUser/axpm-repo/main/axpm.gpg"
```

> **Why `raw.githubusercontent.com` for the key?**  
> GitHub Pages adds caching headers that can delay key updates.  
> `raw.githubusercontent.com` always serves the latest committed file,  
> which is what you want for a signing key.

Then run:

```bash
sudo bash sources/install.sh
```

---

## Final repository layout (what GitHub sees)

```
axpm-repo/                          ← GitHub repo root (GitHub Pages)
├── axpm.gpg                        ← public GPG key (binary)
├── axpm.asc                        ← public GPG key (armored, optional)
├── pool/
│   └── main/
│       └── axpm_1.0_amd64.deb      ← your .deb packages go here
└── dists/
    └── stable/
        ├── Release                 ← signed metadata
        ├── Release.gpg             ← detached signature
        ├── InRelease               ← inline-signed (preferred)
        └── main/
            └── binary-amd64/
                ├── Packages        ← plain index
                ├── Packages.gz     ← gzip index
                └── Packages.bz2    ← bzip2 index (optional)
```

---

## Updating the repo (adding a new package version)

```bash
# 1. Copy the new .deb into pool/
cp axpm_2.0_amd64.deb axpm-repo/pool/main/

# 2. Rebuild indexes and re-sign
./build-repo.sh

# 3. Push
cd axpm-repo && git add . && git commit -m "repo: axpm 2.0" && git push
```

axupdate will pick up the new version on the next refresh.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `NO_PUBKEY` error in apt | Key not imported or wrong fingerprint | Re-run `install.sh`; check `AXPM_KEY_URL` |
| `Release file expired` | Date in Release is stale | Re-run `build-repo.sh` and push |
| `Hash Sum mismatch` | Packages index out of sync with pool | Re-run `build-repo.sh` and push |
| `404 Not Found` | GitHub Pages not enabled or wrong branch | Enable Pages in repo Settings |
| axupdate shows Level 1 for axpm packages | Origin doesn't contain "security" | Expected — axpm packages are standard updates |
