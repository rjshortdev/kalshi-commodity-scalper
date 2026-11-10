#!/usr/bin/env bash
set -euo pipefail

# Config
GIT_USER_NAME="${GIT_USER_NAME:-rjshortdev}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-your-email@example.com}"
DEFAULT_MSG="Update code and docs"
BRANCH="main"
REMOTE="origin"

echo "🚀 Starting deployment..."

# 1. Set Identity if missing
if [ -z "$(git config --get user.name)" ]; then
    git config user.name "$GIT_USER_NAME"
fi
if [ -z "$(git config --get user.email)" ]; then
    git config user.email "$GIT_USER_EMAIL"
fi

# 2. Stage Changes
echo "📦 Staging changes..."
git add .

# 3. Check for changes
if git diff --cached --quiet; then
    echo "ℹ️ No changes detected. Exiting."
    exit 0
fi

# 4. Show Diff & Confirm
echo ""
echo "🔍 Here is what will be committed:"
echo "--------------------------------------------------"
git diff --cached --stat
echo "--------------------------------------------------"

read -rp "✅ Proceed with these changes? (y/n): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "❌ Cancelled. Unstaging files..."
    git reset HEAD . > /dev/null 2>&1 || true
    exit 1
fi

# 5. Get Commit Message
read -rp "💬 Enter commit message (or press Enter for default): " COMMIT_MSG
if [ -z "$COMMIT_MSG" ]; then
    COMMIT_MSG="$DEFAULT_MSG"
fi

# 6. Commit
echo "💾 Committing: '$COMMIT_MSG'"
git commit -m "$COMMIT_MSG"

# 7. Push
echo "☁️ Pushing to $REMOTE/$BRANCH..."

# Try normal push first
if git push "$REMOTE" "$BRANCH"; then
    echo "✅ Successfully pushed!"
else
    echo "⚠️ Normal push failed. Trying force-with-lease..."
    
    # Fetch latest state to ensure safety
    git fetch "$REMOTE" "$BRANCH" || true
    
    # Force push with lease
    if git push --force-with-lease "$REMOTE" "$BRANCH"; then
        echo "✅ Successfully force-pushed!"
    else
        echo "❌ Push failed completely. Check GitHub branch protection."
        exit 1
    fi
fi

echo "✨ Deployment complete."
