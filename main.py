import subprocess
import sys


def main():
    tg = subprocess.Popen([sys.executable, "tg_bot.py"])
    vk = subprocess.Popen([sys.executable, "vk_bot.py"])

    try:
        tg.wait()
        vk.wait()
    except KeyboardInterrupt:
        tg.terminate()
        vk.terminate()


if __name__ == "__main__":
    main()