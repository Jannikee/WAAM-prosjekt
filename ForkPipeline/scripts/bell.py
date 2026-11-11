"""Demo trigger script: show a bell 400x400 px centered on the screen.

Runs via the logger's `run bell.py` trigger action (or double-click).
Press any key or mouse button to close. Stdlib only - no dependencies.
"""

import tkinter


def main():
    root = tkinter.Tk()
    root.title("Bell - press any key to close")
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry("400x400+%d+%d" % ((sw - 400) // 2, (sh - 400) // 2))
    root.resizable(False, False)
    c = tkinter.Canvas(root, width=400, height=400, bg="#f7f3ea", highlightthickness=0)
    c.pack()
    gold = "#e6b422"
    dark = "#7a621a"
    c.create_polygon(200, 58, 238, 96, 246, 150, 262, 214, 286, 272, 114, 272, 138, 214, 154, 150, 162, 96,
                     smooth=True, fill=gold, outline=dark, width=3)
    c.create_oval(186, 36, 214, 64, fill=gold, outline=dark, width=3)
    c.create_oval(96, 262, 304, 306, fill=gold, outline=dark, width=3)
    c.create_oval(182, 304, 218, 340, fill="#c8a017", outline=dark, width=3)

    def close(_event=None):
        root.destroy()

    root.bind("<Key>", close)
    root.bind("<Button>", close)
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()
