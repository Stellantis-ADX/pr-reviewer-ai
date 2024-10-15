#!/bin/bash

# Specify the list of files to exclude
EXCLUDED_FILES=(
  "action.yml"
  "sync_internal_external.sh"
  "test/github_event_path_mock_pull_request.json"
  "test/github_event_path_mock_pull_request_review_comment.json"
)

# Function to check if a file is in the excluded list
is_excluded() {
  local file="$1"
  for excluded in "${EXCLUDED_FILES[@]}"; do
    if [[ "$file" == "$excluded" ]]; then
      return 0
    fi
  done
  return 1
}

# Check if the required arguments are provided
if [ $# -ne 2 ]; then
  echo "Usage: $0 <source_repo> <dest_repo>"
  exit 1
fi

# Set the source and destination repository paths
SOURCE_REPO="$1"
DEST_REPO="$2"

# Check if the source and destination repository paths exist
if [ ! -d "$SOURCE_REPO" ]; then
  echo "Error: Source repository path does not exist"
  exit 1
fi

if [ ! -d "$DEST_REPO" ]; then
  echo "Error: Destination repository path does not exist"
  exit 1
fi

# Copy all files except the excluded ones
for file in $(git -C "$SOURCE_REPO" ls-files); do
  echo "Processing file: $file"
  if is_excluded "$file"; then
    echo "Excluded file: $file"
  else
    echo "Copying file: $file"
    cp -r "$SOURCE_REPO/$file" "$DEST_REPO/$file"
  fi
done