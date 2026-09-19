import os

from dotenv import load_dotenv

# Walks up from the current working directory looking for a .env file,
# so this works whether the app is launched from the project root or src/.
load_dotenv()

ZYFY_API_KEY = os.getenv("ZYFY_API_KEY")
ZYFY_BASE_URL = os.getenv("ZYFY_BASE_URL", "https://zyfy.uk/v1")
