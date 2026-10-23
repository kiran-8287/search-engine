@echo off
cd /d a:\search-engine

echo Configuring git user...
git config user.name "kiran-8287"
git config user.email "kiran8287@example.com"

echo Committing changes...
git commit --message "Initial commit: Elasticsearch IR demo with 7 query types"

echo Setting up remote...
git remote add origin https://github.com/kiran-8287/search-engine.git
git branch -M main

echo Pushing to GitHub...
git push -u origin main

echo Done!
pause
