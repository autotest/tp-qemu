#!/bin/bash

check_status() {
    if [ $? -ne 0 ]; then
        echo "Error: $1"
        exit 1
    fi
}

usage() {
    echo "Usage: $0 [--repo <repository_url>] [--branch <branch_name> | --tag <tag_name>]"
    echo "  --repo   : Git repository URL (default: https://github.com/virtee/snpguest.git)"
    echo "  --branch : Branch name to checkout (default: main)"
    echo "  --tag    : Tag name to checkout"
    echo "Note: --branch and --tag are mutually exclusive."
    exit 1
}

trap 'echo "Cleaning up..."; rm -rf snpguest; exit 1' ERR

REPO_URL="https://github.com/virtee/snpguest.git"
BRANCH="main"
TAG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)
            REPO_URL="$2"
            shift 2
            ;;
        --branch)
            [ -n "$TAG" ] && { echo "Error: Cannot specify both --branch and --tag"; usage; }
            BRANCH="$2"
            shift 2
            ;;
        --tag)
            [ -n "$BRANCH" ] && [ "$BRANCH" != "main" ] && { echo "Error: Cannot specify both --branch and --tag"; usage; }
            TAG="$2"
            BRANCH=""
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

sudo -n true 2>/dev/null || { echo "Error: sudo privileges required"; exit 1; }

echo "Validating repository: $REPO_URL..."
git ls-remote "$REPO_URL" >/dev/null 2>&1
check_status "Invalid or inaccessible repository: $REPO_URL"

if [ -n "$TAG" ]; then
    echo "Validating tag: $TAG..."
    git ls-remote --tags "$REPO_URL" | grep -q "refs/tags/$TAG$"
    check_status "Tag '$TAG' does not exist in repository"
elif [ -n "$BRANCH" ]; then
    echo "Validating branch: $BRANCH..."
    git ls-remote --heads "$REPO_URL" | grep -q "refs/heads/$BRANCH$"
    check_status "Branch '$BRANCH' does not exist in repository"
fi

echo "Installing build essentials..."

if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "Cannot detect operating system."
    exit 1
fi

case "$OS" in
    ubuntu|debian)
        sudo apt update
        check_status "Failed to update package lists"
        sudo apt install -y build-essential git curl
        check_status "Failed to install build-essential"
        ;;
    rhel|centos|fedora|rocky|almalinux)
        sudo yum groupinstall -y "Development Tools"
        check_status "Failed to install Development Tools"
        sudo yum install -y curl git
        check_status "Failed to install dependencies like curl/git"
        ;;
    *)
        echo "Unsupported operating system: $OS"
        exit 1
        ;;
esac

echo "Prerequisites installed successfully."

echo "Installing Rust..."
if command -v rustc >/dev/null 2>&1; then
	echo "Rust is already installed. Skipping installation."
else
	curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
	check_status "Failed to install Rust"
fi

if [ -f "$HOME/.cargo/env" ]; then
    . "$HOME/.cargo/env"
else
    echo "Error: Rust environment file not found"
    exit 1
fi

rustc --version
check_status "Rust installation verification failed"
echo "Rust installed successfully."

echo "Cloning snpguest repository from $REPO_URL"
if [ -d snpguest ]
then
	echo "Removing previous snpguest directory"
	rm -rf snpguest
fi
git clone "$REPO_URL" snpguest
check_status "Failed to clone snpguest repository"
[ -d "snpguest" ] || { echo "Error: snpguest directory not found"; exit 1; }
cd snpguest || { echo "Error: Failed to enter snpguest directory"; exit 1; }

if [ -n "$TAG" ]; then
    echo "Checking out tag: $TAG..."
    git checkout "tags/$TAG"
    check_status "Failed to checkout tag $TAG"
elif [ -n "$BRANCH" ]; then
    echo "Checking out branch: $BRANCH..."
    git checkout "$BRANCH"
    check_status "Failed to checkout branch $BRANCH"
fi

echo "Building snpguest..."
cargo build --release
check_status "Failed to build snpguest"

[ -w /usr/local/bin ] || { echo "Error: /usr/local/bin is not writable"; exit 1; }
cp "$PWD/target/release/snpguest" /usr/local/bin
check_status "Failed to copy snpguest to /usr/local/bin"

snpguest --version
check_status "snpguest installation verification failed"
echo "snpguest installed successfully."

exit 0
