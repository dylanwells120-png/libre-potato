"""Open the Libre Potato window: python -m potato_client"""

from potato_client.gui import App


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
