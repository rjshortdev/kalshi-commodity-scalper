#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------
GIT_USER_NAME="${GIT_USER_NAME:-rjshortdev}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-your-email@example.com}" # CHANGE THIS TO YOUR EMAIL
DEFAULT_MSG="Update code and docs"

echo "🚀 Starting deployment for kalshi-commodity-scalper..."

# -----------------------------------------------------------------------------
# 1. Ensure Git Identity is Set
# -----------------------------------------------------------------------------
if [ -z "$(git config --get user.name)" ]; then
    echo "⚙️ Setting local git user name: $GIT_USER_NAME"
    git config user.name "$GIT_USER_NAME"
fi

if [ -z "$(git config --get user.email)" ]; then
    echo "⚙️ Setting local git user email: $GIT_USER_EMAIL"
    git config user.email "$GIT_USER_EMAIL"
fi

# -----------------------------------------------------------------------------
# 2. Stage Changes & Show Diff Summary
# -----------------------------------------------------------------------------
echo "📦 Staging changes..."
git add .

# Check if there are actually staged changes
if git diff --cached --quiet; then
    echo "ℹ️ No changes detected. Nothing to commit."
    exit 0
fi

# --- SHOW WHAT CHANGED ---
echo ""
echo "🔍 Here is what will be committed:"
echo "--------------------------------------------------"
git diff --cached --stat
echo "--------------------------------------------------"
echo ""

# Ask for confirmation
read -rp "✅ Proceed with these changes? (y/n): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "❌ Commit cancelled by user."
    git reset HEAD . > /dev/null 2>&1 || true
    exit 1
fi

# -----------------------------------------------------------------------------
# 3. Get Commit Message
# -----------------------------------------------------------------------------
COMMIT_MSG=""
while [ -z "$COMMIT_MSG" ]; do
    read -rp "💬 Enter commit message (or press Enter for '$DEFAULT_MSG'): " COMMIT_MSG
    if [ -z "$COMMIT_MSG" ]; then
        COMMIT_MSG="$DEFAULT_MSG"
    fi
done

# -----------------------------------------------------------------------------
# 4. Commit
# -----------------------------------------------------------------------------
echo "💾 Committing: '$COMMIT_MSG'"
git commit -m "$COMMIT_MSG"

# -----------------------------------------------------------------------------
# 5. Push to Remote
# -----------------------------------------------------------------------------
BRANCH="main"
REMOTE="origin"

echo "☁️ Pushing to $REMOTE/$BRANCH..."

# Try standard push first
if git push "$REMOTE" "$BRANCH"; then

