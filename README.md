# GitHub Profile Curator

A Codex skill for turning a few shipped repositories into a GitHub profile people can navigate. It helps select project pins, write descriptions based on public evidence, and update one README section with a local Python tool.

## Install and run in Codex

Clone this repository, then copy `skills/github-profile-curator` into your Codex skills directory. From the checkout, this installs it in the default user directory if the skill does not already exist there:

```sh
skill_root="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$skill_root"
test ! -e "$skill_root/github-profile-curator" && \
  cp -R skills/github-profile-curator "$skill_root/"
```

Start a Codex session and try:

> Use $github-profile-curator for my GitHub profile. Feature the repositories I name, explain what each demonstrates, and show me a README diff and proposed pin order.

## Try the offline renderer

Requires Python 3.11 or later. The example account and repository names are illustrative.

```sh
python3 skills/github-profile-curator/scripts/render_profile.py \
  --readme examples/profile.md --projects examples/projects.json \
  --before '## Selected projects' > profile.preview.md
diff -u examples/profile.md profile.preview.md
python3 -m unittest discover -s tests -v
```

The preview has one managed project section. Run the command with the preview as input and a different output path to check that the same inputs produce the same bytes. The renderer runs offline and writes the candidate to stdout. Codex can apply a reviewed GitHub change when asked. Pin edits use GitHub’s own profile controls.
