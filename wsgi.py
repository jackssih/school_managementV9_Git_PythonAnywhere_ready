import os
import sys

project_home = "/home/EurekaScholaPrimaSolution/mysite"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("FLASK_ENV", "production")

from app import app as application
