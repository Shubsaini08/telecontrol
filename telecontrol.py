
import os
import time
import logging
import subprocess
import requests
import shutil
from threading import Thread

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# ===== BOT CONFIGURATION =====
BOT_TOKEN = "--------"  # Replace with your actual bot token
ADMIN_IDS = ["----", "---"]  # Authorized admin chat IDs

# Global flags
OFFLINE_MODE = False          # When True, only /start command is accepted
WRITECONTROL_ACTIVE = False   # When True, plain text messages are treated as shell commands

# Global variables for multi-device support
# Each device context holds its current working directory and last active time.
current_device = "1"
device_contexts = {
    "1": {"current_directory": os.getcwd(), "last_active": time.time()}
}

# ===== Utility Functions =====
def send_message(text: str):
    """Send a text message to all authorized admin chat IDs."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for admin_id in ADMIN_IDS:
        data = {"chat_id": admin_id, "text": text}
        try:
            requests.post(url, data=data)
        except Exception as e:
            logging.error(f"Error sending message to {admin_id}: {e}")

def send_file(file_path: str):
    """Send a file as a document to all authorized admin chat IDs."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    for admin_id in ADMIN_IDS:
        try:
            with open(file_path, "rb") as f:
                files = {"document": f}
                data = {"chat_id": admin_id}
                requests.post(url, data=data, files=files)
        except Exception as e:
            logging.error(f"Error sending file {file_path} to {admin_id}: {e}")

def compute_directory_size(path: str) -> int:
    """Recursively compute the total size (in bytes) of a directory."""
    total_size = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    return total_size

def send_file_content(file_path: str) -> str:
    """Read the content of a file and return it as a string."""
    try:
        with open(file_path, "r", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def is_authorized(update: Update) -> bool:
    """Check if the sender is an authorized admin based on chat ID."""
    return str(update.message.chat_id) in ADMIN_IDS

def restricted_command(func):
    """
    Decorator that restricts command access to authorized admin chat IDs.
    It also checks if the bot is in OFFLINE_MODE (only /start is allowed when offline).
    """
    async def wrapper(update: Update, context: CallbackContext):
        if not is_authorized(update):
            await update.message.reply_text("⛔ Access Denied! You are not authorized to use this bot.")
            return
        global OFFLINE_MODE
        # Allow /start even when offline; block all other commands if offline.
        if OFFLINE_MODE and update.message.text.split()[0] != "/start":
            await update.message.reply_text("⚠️ Bot is currently offline. Only /start command can bring it back online.")
            return
        return await func(update, context)
    return wrapper

# ===== Command Handlers =====

@restricted_command
async def start_command(update: Update, context: CallbackContext):
    """
    /start command:
    - Accepts an optional device number parameter (e.g. '/start 1').
    - Sets the active device context (creating it if needed).
    - If the bot is offline, brings it online; otherwise, notifies that the bot has started.
    """
    global OFFLINE_MODE, WRITECONTROL_ACTIVE, current_device, device_contexts
    args = context.args
    device_id = "1"
    if args:
        device_id = args[0]
    current_device = device_id
    if device_id not in device_contexts:
        device_contexts[device_id] = {"current_directory": os.getcwd(), "last_active": time.time()}
    else:
        device_contexts[device_id]["last_active"] = time.time()
    if OFFLINE_MODE:
        OFFLINE_MODE = False
        WRITECONTROL_ACTIVE = False  # Reset write control mode if it was active
        await update.message.reply_text(f"✅ Bot is back online on device {device_id}. Welcome back!")
        send_message(f"🔔 Bot restarted on device {device_id} at {time.ctime()}.")
    else:
        await update.message.reply_text(f"✅ Bot started on device {device_id}. You now have full control over the system!")
        send_message(f"🔔 Bot started on device {device_id} at {time.ctime()}.")

@restricted_command
async def match_command(update: Update, context: CallbackContext):
    """
    /match command:
    - If the command includes a file path as argument, search for that file immediately.
    - Otherwise, ask the admin to provide the complete file path.
    """
    args = context.args
    if args:
        file_path = " ".join(args)
        if os.path.exists(file_path):
            await update.message.reply_text(f"✅ File found at {file_path}. Sending file...")
            send_file(file_path)
        else:
            await update.message.reply_text(f"❌ File not found at {file_path}.")
    else:
        await update.message.reply_text("📂 Please provide the complete file path you want to search for:")
        context.user_data["awaiting_match"] = True

@restricted_command
async def git_command(update: Update, context: CallbackContext):
    """
    /git command:
    - Ask for the GitHub repository URL to clone.
    - The subsequent plain text message will be interpreted as the repository URL.
    """
    await update.message.reply_text("🔗 Please provide the GitHub repository URL to clone:")
    context.user_data["awaiting_git_repo"] = True

@restricted_command
async def writecontrol_command(update: Update, context: CallbackContext):
    """
    /writecontrol command:
    - Activates write control mode, where any plain text message is executed as a shell command.
    """
    global WRITECONTROL_ACTIVE
    WRITECONTROL_ACTIVE = True
    await update.message.reply_text("✅ WriteControl activated. You now have full system command execution control.")

@restricted_command
async def cat_command(update: Update, context: CallbackContext):
    """
    /cat command:
    - Prompts the admin to provide a full file path.
    - Then reads and sends the file’s content in a copyable format (or as a document if too long).
    """
    await update.message.reply_text("📄 Please provide the full path of the file you want to view:")
    context.user_data["awaiting_cat"] = True

@restricted_command
async def stop_command(update: Update, context: CallbackContext):
    """
    /stop command:
    - Puts the bot into offline mode (minimal network usage).
    - Notifies the admin that only /start will bring it back online.
    """
    global OFFLINE_MODE, WRITECONTROL_ACTIVE
    OFFLINE_MODE = True
    WRITECONTROL_ACTIVE = False
    await update.message.reply_text("🚫 Bot is now going offline. Internet usage reduced to minimal. Only /start will bring it back online.")
    send_message(f"🔔 Bot stopped at {time.ctime()}. Running in offline mode.")

@restricted_command
async def cd_command(update: Update, context: CallbackContext):
    """
    /cd command:
    - Changes the working directory for the active device.
    - Accepts absolute or relative paths (including '..' to move upward).
    """
    global current_device, device_contexts
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /cd <directory path>")
        return
    # Get current device context; default to device "1" if none exists.
    device_id = current_device if current_device is not None else "1"
    current_dir = device_contexts.get(device_id, {"current_directory": os.getcwd()})["current_directory"]
    # Join the arguments to form the target path.
    target_path = " ".join(args)
    # If the provided path is absolute, use it; otherwise, join with current directory.
    if not os.path.isabs(target_path):
        new_path = os.path.join(current_dir, target_path)
    else:
        new_path = target_path
    new_path = os.path.abspath(new_path)
    if os.path.isdir(new_path):
        device_contexts[device_id]["current_directory"] = new_path
        device_contexts[device_id]["last_active"] = time.time()
        await update.message.reply_text(f"✅ Changed directory to {new_path}")
    else:
        await update.message.reply_text(f"❌ Directory {new_path} does not exist.")

@restricted_command
async def ls_command(update: Update, context: CallbackContext):
    """
    /ls command:
    - Lists the contents of the current working directory for the active device.
    - For each entry, shows an icon (💽 for directories, 📁 for files), name, and size.
    """
    global current_device, device_contexts
    device_id = current_device if current_device is not None else "1"
    current_dir = device_contexts.get(device_id, {"current_directory": os.getcwd()})["current_directory"]
    try:
        entries = os.listdir(current_dir)
    except Exception as e:
        await update.message.reply_text(f"❌ Error listing directory: {e}")
        return
    if not entries:
        await update.message.reply_text("ℹ️ Directory is empty.")
        return
    result = f"Contents of {current_dir}:\n"
    for entry in entries:
        full_path = os.path.join(current_dir, entry)
        if os.path.isdir(full_path):
            size = compute_directory_size(full_path)
            icon = "💽"  # directory icon
            result += f"{icon} {entry}/ - {size} bytes\n"
        elif os.path.isfile(full_path):
            size = os.path.getsize(full_path)
            icon = "📁"  # file icon (as requested)
            result += f"{icon} {entry} - {size} bytes\n"
        else:
            result += f"{entry} - Unknown type\n"
    await update.message.reply_text(result)

@restricted_command
async def pwd_command(update: Update, context: CallbackContext):
    """
    /pwd command:
    - Displays the current working directory for the active device.
    """
    global current_device, device_contexts
    device_id = current_device if current_device is not None else "1"
    current_dir = device_contexts.get(device_id, {"current_directory": os.getcwd()})["current_directory"]
    await update.message.reply_text(f"Current directory: {current_dir}")

@restricted_command
async def devices_command(update: Update, context: CallbackContext):
    """
    /devices command:
    - Lists all active device contexts sorted by their last active time (oldest first).
    """
    global device_contexts
    if not device_contexts:
        await update.message.reply_text("No devices found.")
        return
    sorted_devices = sorted(device_contexts.items(), key=lambda x: x[1]["last_active"])
    result = "Active Devices:\n"
    for device_id, info in sorted_devices:
        result += (f"Device {device_id} - Current Directory: {info['current_directory']}, "
                   f"Last Active: {time.ctime(info['last_active'])}\n")
    await update.message.reply_text(result)

@restricted_command
async def handle_text(update: Update, context: CallbackContext):
    """
    Handler for plain text messages. Based on waiting state:
    - If awaiting a GitHub URL (for /git), clones the repo and reports its size.
    - If awaiting a file path (for /match), searches and sends the file.
    - If awaiting a file path (for /cat), reads and sends the file content.
    - If WriteControl mode is active, treats the text as a shell command.
    - Otherwise, notifies that no action is assigned.
    """
    global WRITECONTROL_ACTIVE

    # Handle GitHub repository cloning
    if context.user_data.get("awaiting_git_repo"):
        repo_url = update.message.text.strip()
        try:
            repo_name = repo_url.rstrip("/").split("/")[-1]
            subprocess.check_call(["git", "clone", repo_url])
            if os.path.isdir(repo_name):
                size_bytes = compute_directory_size(repo_name)
                size_str = f"{size_bytes} bytes"
            else:
                size_str = "Unknown size"
            await update.message.reply_text(f"✅ GitHub repository '{repo_url}' cloned successfully.\nRepository size: {size_str}.")
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(f"❌ Error cloning repository: {e}")
        except Exception as e:
            await update.message.reply_text(f"❌ Unexpected error: {e}")
        finally:
            context.user_data["awaiting_git_repo"] = False
        return

    # Handle file search for /match command
    if context.user_data.get("awaiting_match"):
        file_path = update.message.text.strip()
        if os.path.exists(file_path):
            await update.message.reply_text(f"✅ File found at {file_path}. Sending file...")
            send_file(file_path)
        else:
            await update.message.reply_text(f"❌ File not found at {file_path}.")
        context.user_data["awaiting_match"] = False
        return

    # Handle file content display for /cat command
    if context.user_data.get("awaiting_cat"):
        file_path = update.message.text.strip()
        if os.path.exists(file_path):
            content = send_file_content(file_path)
            if len(content) > 4000:
                temp_filename = "temp_file_content.txt"
                with open(temp_filename, "w", encoding="utf-8") as f:
                    f.write(content)
                send_file(temp_filename)
                os.remove(temp_filename)
                await update.message.reply_text("📄 File content is long; sent as document.")
            else:
                await update.message.reply_text(f"📄 File content:\n{content}")
        else:
            await update.message.reply_text(f"❌ File not found at {file_path}.")
        context.user_data["awaiting_cat"] = False
        return

    # Execute shell commands if WriteControl mode is active.
    # The command is now executed in the current working directory for the active device.
    if WRITECONTROL_ACTIVE:
        command = update.message.text.strip()
        try:
            current_dir = device_contexts.get(current_device, {"current_directory": os.getcwd()})["current_directory"]
            process = subprocess.Popen(
                command, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=current_dir  # Execute in the current directory from /cd
            )
            stdout, stderr = process.communicate(timeout=30)
            response = ""
            if stdout:
                response += f"Output:\n{stdout.decode()}\n"
            if stderr:
                response += f"Error:\n{stderr.decode()}\n"
            if not response:
                response = "No output."
            await update.message.reply_text(response)
        except subprocess.TimeoutExpired:
            await update.message.reply_text("❌ Command execution timed out.")
        except Exception as e:
            await update.message.reply_text(f"❌ Execution error: {e}")
        return

    # If no waiting state applies, notify no action is assigned.
    await update.message.reply_text("ℹ️ No action assigned for this message.")

# ===== Background Connectivity Monitor =====
def monitor_connectivity():
    """
    Periodically check network connectivity (via a simple ping) and
    notify the admins if the connection appears to be down.
    """
    while True:
        try:
            response = subprocess.run(["ping", "-c", "1", "8.8.8.8"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if response.returncode != 0:
                send_message("⚠️ Internet connectivity appears to be down.")
        except Exception as e:
            send_message(f"⚠️ Connectivity check error: {e}")
        time.sleep(60)  # Check every 60 seconds

# ===== Main Function =====
def main():
    # Start background connectivity monitoring in a separate thread.
    connectivity_thread = Thread(target=monitor_connectivity, daemon=True)
    connectivity_thread.start()

    # Build and run the Telegram bot application.
    application = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers.
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("match", match_command))
    application.add_handler(CommandHandler("git", git_command))
    application.add_handler(CommandHandler("writecontrol", writecontrol_command))
    application.add_handler(CommandHandler("cat", cat_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("cd", cd_command))
    application.add_handler(CommandHandler("ls", ls_command))
    application.add_handler(CommandHandler("pwd", pwd_command))
    application.add_handler(CommandHandler("devices", devices_command))
    
    # Register a handler for all plain text messages.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Start polling for updates (the bot will run continuously).
    application.run_polling()

if __name__ == "__main__":
    main()


