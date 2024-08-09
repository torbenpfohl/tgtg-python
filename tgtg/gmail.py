"""
Copied from https://developers.google.com/gmail/api/quickstart/python

Modified.
"""

import re
import os.path
from base64 import urlsafe_b64decode
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
RETRIES = 10
OFFSET = 60  # seconds

path = Path(__file__).parent

def get_gmail_url(timestamp: int) -> str:
  """Shows basic usage of the Gmail API.
  Lists the user's Gmail labels.
  """

  creds = None
  # The file token.json stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  if os.path.exists("token.json"):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
  # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(
          os.path.join(path, "credentials.json"), SCOPES
      )
      creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open("token.json", "w") as token:
      token.write(creds.to_json())

  try:
    # Call the Gmail API
    service = build("gmail", "v1", credentials=creds)

    # Get message ids.
    results = service.users().messages().list(userId="me", q=f"from:toogoodtogo after:{timestamp}").execute()
    messages = results.get("messages", [])
    messageIds = [m["id"] for m in messages]
    messages = list()

    # No message ids means no tgtg-email. Return and try again later.
    if len(messageIds) == 0:
      return None

    # Get messages from message ids.
    for id in messageIds:
      message = service.users().messages().get(userId="me", id=id).execute()
      messages.append(message)
    newestMessage = sorted(messages, key=lambda m: m["internalDate"])[-1]

    # Get a short message version that contains the accept login url and extract that url.
    shortVersion = newestMessage["payload"]["parts"][0]["body"]["data"]
    shortVersion = urlsafe_b64decode(shortVersion)
    shortVersion = shortVersion.decode(encoding="utf-8")
    # acceptLoginUrl = re.search(r"https://share.toogoodtogo.com/login/accept/[a-f0-9/-]+", shortVersion)
    # if acceptLoginUrl:
    #   acceptLoginUrl = acceptLoginUrl.group()
    # # print code as well 
    code = re.search(r"\d{6,6}(?=\s)", shortVersion)
    if code:
      code = code.group()
      print("Code from email: ", code)
    return code

  except HttpError as error:
    # TODO(developer) - Handle errors from gmail API.
    print(f"An error occurred: {error}")


if __name__ == "__main__":
  pass

