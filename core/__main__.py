from .runtime import get_runtime


def main():

    runtime = get_runtime()

    print("=" * 40)
    print("VAELOR CORE ONLINE")
    print("=" * 40)

    print(f"Name: {runtime.name}")
    print(f"Title: {runtime.title}")

    print()
    print("The archive awaits your question.")
    print()

    while True:

        user = input("Apprentice > ")

        if user.lower() in ["exit", "quit"]:

            print("Vaelor sleeps.")
            break


        response = runtime.brain.think(
            user
        )

        print()
        print(response)
        print()



if __name__ == "__main__":
    main()