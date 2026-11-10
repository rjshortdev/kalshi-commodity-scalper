#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------
# Replace these with your actual GitHub details if not already set globally
GIT_USER_NAME="${GIT_USER_NAME:-rjshortdev}"       # Default to your username
GIT_USER_EMAIL="${GIT_USER_EMAIL:-your-email@example.com}" # CHANGE THIS TO YOUR EMAIL
COMMIT_MSG="${1:-"Update code and docs"}"          # Pass message as arg 1, or default

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
# 2. Stage Changes
# -----------------------------------------------------------------------------
echo "📦 Staging changes..."
git add .

# -----------------------------------------------------------------------------
# 3. Commit (Only if there are staged changes)
# -----------------------------------------------------------------------------
if ! git diff --cached --quiet; then
    echo "💾 Committing: '$COMMIT_MSG'"
    git commit -m "$COMMIT_MSG"
else
    echo "ℹ️ No changes detected. Skipping commit."
fi

# -----------------------------------------------------------------------------
# 4. Push to Remote
# -----------------------------------------------------------------------------
BRANCH="main"
REMOTE="origin"

echo "☁️ Pushing to $REMOTE/$BRANCH..."

# Try standard push first (safer)
if git push "$REMOTE" "$BRANCH"; then
    echo "✅ Successfully pushed to remote!"
else
    echo "⚠️ Standard push failed. Attempting force push (--force-with-lease)..."
    
    # Fetch latest state from remote to ensure we don't overwrite someone else's work blindly
    git fetch "$REMOTE" "$BRANCH" || true
    
    # Force push with lease (only overwrites if remote hasn't changed since our last fetch)
    if git push --force-with-lease "$REMOTE" "$BRANCH"; then
        echo "✅ Successfully force-pushed to remote!"
    else
        echo "❌ Failed to push even with force. Check branch protection settings on GitHub."
        exit 1
    fi
fi

echo "✨ Deployment complete."
