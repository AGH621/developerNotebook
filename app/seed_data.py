"""Starter notebook topics, sections, and command rows for onboarding.

The authoritative source Word file ``Developer_Commands.docx`` is not tracked in
git; content here mirrors that structure (~18 topics) for predictable seeding.
Topics without logical sub-headings use a single section with ``name: None``.
"""

STARTER_DATA: list[dict] = [
    {
        "name": "Git",
        "sections": [
            {
                "name": "Branches",
                "entries": [
                    {
                        "description": "Delete a merged local branch",
                        "command": "git branch -d <branch-name>",
                    },
                    {
                        "description": "Force-delete a branch",
                        "command": "git branch -D <branch-name>",
                    },
                    {
                        "description": "List local branches",
                        "command": "git branch --list",
                    },
                    {
                        "description": "Create and checkout a branch",
                        "command": "git checkout -b <branch-name>",
                    },
                    {"description": "Rename current branch", "command": "git branch -m <new-name>"},
                ],
            },
            {
                "name": "Commits",
                "entries": [
                    {"description": "Stage all changes", "command": "git add -A"},
                    {"description": "Commit staged work", 'command': 'git commit -m "<message>"'},
                    {
                        "description": "Stage + commit tracked files quickly",
                        "command": 'git commit -am "<message>"',
                    },
                    {"description": "Show commit history compact", "command": "git log --oneline -n20"},
                    {
                        "description": "Undo last commit, keep changes staged",
                        "command": "git reset --soft HEAD~1",
                    },
                ],
            },
            {
                "name": "Remote",
                "entries": [
                    {"description": "Push current branch upstream", "command": "git push -u origin HEAD"},
                    {"description": "Pull latest commits", "command": "git pull --ff-only"},
                    {"description": "Fetch without merging", "command": "git fetch --all"},
                    {"description": "Show remotes", "command": "git remote -v"},
                ],
            },
            {
                "name": "Stash",
                "entries": [
                    {"description": "Stash local changes", "command": "git stash push -m '<note>'"},
                    {"description": "List stash stack", "command": "git stash list"},
                    {"description": "Apply latest stash keep it", "command": "git stash apply stash@{0}"},
                    {"description": "Pop latest stash", "command": "git stash pop"},
                ],
            },
        ],
    },
    {
        "name": "Shell",
        "sections": [
            {
                "name": "Files",
                "entries": [
                    {"description": "Find files by name fragment", "command": "find . -name '*.py'"},
                    {"description": "Recursive search pattern", "command": "grep -r 'pattern' ."},
                    {"description": "Show disk usage of folder", "command": "du -sh <path>"},
                    {"description": "Count lines fast", "command": "wc -l <file>"},
                ],
            },
            {
                "name": "Permissions",
                "entries": [
                    {"description": "Make script executable", "command": "chmod +x ./script.sh"},
                    {"description": "Change owner recursively", "command": "chown -R user:group <path>"},
                ],
            },
            {
                "name": "Processes",
                "entries": [
                    {"description": "List listening ports + PIDs", "command": "lsof -i -P | grep LISTEN"},
                    {"description": "Kill process by PID", "command": "kill -9 <pid>"},
                ],
            },
        ],
    },
    {
        "name": "Python",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Create virtual environment", "command": "python -m venv .venv"},
                    {"description": "Activate venv Linux/macOS", "command": "source .venv/bin/activate"},
                    {"description": "Install requirements", "command": "pip install -r requirements.txt"},
                    {"description": "Run REPL", "command": "python"},
                    {"description": "Format with default black example", "command": "black ."},
                    {"description": "Run module path", "command": "python -m http.server"},
                ],
            },
        ],
    },
    {
        "name": "Docker",
        "sections": [
            {
                "name": "Containers",
                "entries": [
                    {"description": "List running containers", "command": "docker ps"},
                    {"description": "Start shell inside container", "command": "docker exec -it <cid> bash"},
                    {"description": "Stop container", "command": "docker stop <cid>"},
                ],
            },
            {
                "name": "Images",
                "entries": [
                    {"description": "Build from Dockerfile cwd", "command": "docker build -t <tag> ."},
                    {"description": "List images", "command": "docker images"},
                    {"description": "Remove unused images", "command": "docker image prune"},
                ],
            },
            {
                "name": "Compose",
                "entries": [
                    {"description": "Start compose stack detach", "command": "docker compose up -d"},
                    {"description": "View logs follow", "command": "docker compose logs -f"},
                    {"description": "Stop stack", "command": "docker compose down"},
                ],
            },
        ],
    },
    {
        "name": "PostgreSQL",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Connect default database", "command": "psql -d postgres"},
                    {"description": "List databases", "command": '\\l'},
                    {"description": "Describe table", "command": '\\d+ <table>'},
                    {"description": "Export CSV copy", 'command': "\\copy (SELECT * FROM t) TO '/tmp/out.csv' CSV HEADER"},
                    {"description": "Run SQL script file", "command": "psql -f schema.sql"},
                ],
            },
        ],
    },
    {
        "name": "npm & Node.js",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Init package.json defaults", "command": "npm init -y"},
                    {"description": "Install dependency", "command": "npm install <pkg>"},
                    {"description": "Run package script named dev", "command": "npm run dev"},
                    {"description": "Global install CLI", "command": "npm install -g <pkg>"},
                    {"description": "Audit vulnerabilities", "command": "npm audit"},
                ],
            },
        ],
    },
    {
        "name": "SSH",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Connect as user host", "command": "ssh user@host"},
                    {"description": "Use specific key", "command": "ssh -i ~/.ssh/id_ed25519 user@host"},
                    {"description": "Copy file to remote", "command": "scp local.txt user@host:~/"},
                    {"description": "Tunnel local port to remote svc", 'command': "ssh -L 5432:localhost:5432 user@host"},
                ],
            },
        ],
    },
    {
        "name": "curl",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "GET show headers body", "command": "curl -i https://example.com"},
                    {"description": "POST JSON", 'command': "curl -H 'Content-Type: application/json' -d '{}' URL"},
                    {"description": "Save output file", 'command': "curl -o out.bin URL"},
                    {"description": "Follow redirects", "command": "curl -L URL"},
                ],
            },
        ],
    },
    {
        "name": "GitHub CLI",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Auth browser", "command": "gh auth login"},
                    {"description": "View PR checks", "command": "gh pr checks"},
                    {"description": "Create PR interactive", "command": "gh pr create"},
                    {"description": "Clone repo shorthand", 'command': "gh repo clone owner/repo"},
                ],
            },
        ],
    },
    {
        "name": "Django",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Run dev server", "command": "python manage.py runserver"},
                    {"description": "Create migrations after model edits", "command": "python manage.py makemigrations"},
                    {"description": "Apply migrations", "command": "python manage.py migrate"},
                    {"description": "Django shell", "command": "python manage.py shell"},
                    {"description": "Create superuser", "command": "python manage.py createsuperuser"},
                ],
            },
        ],
    },
    {
        "name": "Flask",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Run app with Flask CLI", 'command': "export FLASK_APP=app:create_app && flask run"},
                    {"description": "Debug env var", 'command': "export FLASK_DEBUG=1"},
                    {"description": "Shell context", "command": "flask shell"},
                ],
            },
        ],
    },
    {
        "name": "MongoDB",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Connect mongosh URIs style", 'command': "mongosh '<mongodb-uri>'"},
                    {"description": "List databases shell", 'command': "show dbs"},
                    {"description": "Use collection counts", 'command': "db.<coll>.estimatedDocumentCount()"},
                ],
            },
        ],
    },
    {
        "name": "Redis",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "CLI connect local", 'command': "redis-cli"},
                    {"description": "Ping server", "command": 'redis-cli ping'},
                    {"description": "Get string key", "command": "redis-cli get <key>"},
                    {"description": "Monitor realtime commands", "command": 'redis-cli monitor'},
                ],
            },
        ],
    },
    {
        "name": "pytest",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Run tests verbose stop first fail", 'command': "pytest -xvs"},
                    {"description": "Run single test node id", 'command': "pytest path/test_file.py::test_name"},
                    {"description": "Coverage summary", 'command': "pytest --cov=."},
                    {"description": "Last failures only", 'command': "pytest --lf"},
                ],
            },
        ],
    },
    {
        "name": "Vim basics",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Save quit", 'command': ':wq'},
                    {"description": "Quit without save force", 'command': ':q!'},
                    {"description": "Undo", 'command': 'u'},
                    {"description": "Search forward", "command": "/pattern"},
                    {"description": "Go line number", "command": ":42"},
                ],
            },
        ],
    },
    {
        "name": "kubectl",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Current context clusters", 'command': "kubectl config current-context"},
                    {"description": "Pods default namespace", 'command': 'kubectl get pods'},
                    {'description': "Logs follow pod", 'command': 'kubectl logs -f deployment/<name>'},
                    {"description": "Describe pod events", 'command': 'kubectl describe pod <pod-name>'},
                ],
            },
        ],
    },
    {
        "name": "jq",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Pretty-print JSON stdin", 'command': "jq '.' < file.json"},
                    {"description": "Select field pipe", 'command': "jq '.items[].metadata.name'"},
                    {"description": "Filter arrays", 'command': "jq 'map(select(.active))'"},
                ],
            },
        ],
    },
    {
        "name": "SQLite",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Open database REPL", 'command': 'sqlite3 data.db'},
                    {"description": "Import CSV table", "command": ".import file.csv tbl"},
                    {"description": "Dump schema sql", "command": ".schema"},
                    {"description": "Output column headers ON", "command": ".headers on"},
                ],
            },
        ],
    },
]
