#!/usr/bin/env python3
import curses
import chess
import chess.pgn
import requests
import json              # <-- Import json for dumping data
from io import StringIO

# Example ASCII "shapes" for each piece. 
ASCII_PIECES = {
    'P': [
        " ^ ",
        "(P)",
        "/_\\"
    ],
    'N': [
        " __",
        "/ N",
        "\\_/"
    ],
    'B': [
        "  ^",
        " /B\\",
        " \\_/"
    ],
    'R': [
        "[R]",
        "[R]",
        "[R]"
    ],
    'Q': [
        " Q ",
        "( )",
        " \\|"
    ],
    'K': [
        " K ",
        "(. )",
        " | "
    ],
    # Black pieces
    'p': [
        " ^ ",
        "(p)",
        "/_\\"
    ],
    'n': [
        " __",
        "/ n",
        "\\_/"
    ],
    'b': [
        "  ^",
        " /b\\",
        " \\_/"
    ],
    'r': [
        "[r]",
        "[r]",
        "[r]"
    ],
    'q': [
        " q ",
        "( )",
        " \\|"
    ],
    'k': [
        " k ",
        "(. )",
        " | "
    ],
}

def init_colors():
    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_MAGENTA)  # Pink squares
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_YELLOW)   # Yellow squares

def draw_piece_ascii(stdscr, piece_char, x, y, cell_width, cell_height, bg_color):
    """
    Draws ASCII art for a given piece in a cell at (x, y).
    """
    shape = ASCII_PIECES.get(piece_char)
    if not shape:
        return
    shape_height = len(shape)
    shape_width = max(len(line) for line in shape)
    offset_y = (cell_height - shape_height) // 2
    offset_x = (cell_width - shape_width) // 2
    for row_idx, row_text in enumerate(shape):
        if 0 <= offset_y + row_idx < cell_height:
            clipped = row_text[:cell_width]
            stdscr.addstr(
                y + offset_y + row_idx,
                x + offset_x,
                clipped,
                bg_color
            )

def draw_board_common(stdscr, board, cell_width, cell_height):
    """
    A helper that draws the board and returns the (prompt_y) row
    we should write prompts at. 
    """
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    # Validate that the board can fit.
    required_width = 8 * cell_width + 4
    required_height = 8 * cell_height + 4
    if height < required_height or width < required_width:
        stdscr.addstr(0, 0, "Window too small to draw the chessboard.")
        stdscr.refresh()
        return -1

    # Draw squares
    for row in range(8):
        for col in range(8):
            x = col * cell_width + 3  # offset for file labels
            y = row * cell_height + 1 # offset for rank labels
            piece = board.piece_at(chess.square(col, 7 - row))
            # Checkerboard colors
            if (row + col) % 2 == 0:
                bg_color = curses.color_pair(2)  # Yellow
            else:
                bg_color = curses.color_pair(1)  # Pink

            # Fill entire cell with background color
            for h_offset in range(cell_height):
                stdscr.addstr(y + h_offset, x, ' ' * cell_width, bg_color)

            # If there's a piece, draw it
            if piece:
                draw_piece_ascii(
                    stdscr, piece.symbol(),
                    x, y,
                    cell_width, cell_height,
                    bg_color
                )

    # Draw rank indicators on the left (8..1)
    for row in range(8):
        stdscr.addstr(row * cell_height + 1, 1, str(8 - row))
    # Draw file indicators (A..H) at the bottom
    for col in range(8):
        stdscr.addstr(8 * cell_height + 2, col * cell_width + 3, chr(ord('A') + col))

    # Return a row for prompt usage
    prompt_y = 8 * cell_height + 4
    return prompt_y

def draw_standard_game(stdscr, board, cell_width=None, cell_height=None):
    """
    Original TUI loop for a normal game. 
    """
    init_colors()
    while not board.is_game_over():
        # Decide cell sizes if None
        height, width = stdscr.getmaxyx()
        if cell_width is None:
            cell_width = max(3, (width - 4) // 8)
        if cell_height is None:
            cell_height = max(3, (height - 4) // 8)

        prompt_y = draw_board_common(stdscr, board, cell_width, cell_height)
        if prompt_y < 0:
            return  # Board didn't fit

        # Prompt user
        color = "White" if board.turn else "Black"
        stdscr.addstr(prompt_y, 0, f"Enter {color}'s move (e.g., e4):")
        stdscr.clrtoeol()
        stdscr.refresh()
        
        # Get user move
        stdscr.move(prompt_y + 1, 0)
        stdscr.clrtoeol()
        curses.echo()
        move_str = stdscr.getstr(prompt_y + 1, 0).decode('utf-8')
        curses.noecho()

        # Try parse
        try:
            san_move = board.parse_san(move_str)
            if san_move in board.legal_moves:
                board.push(san_move)
            else:
                stdscr.addstr(prompt_y + 2, 0, "Illegal move. Press any key.")
                stdscr.refresh()
                stdscr.getch()
        except ValueError:
            stdscr.addstr(prompt_y + 2, 0, "Invalid or unrecognized move. Press any key.")
            stdscr.refresh()
            stdscr.getch()

    # Game over
    stdscr.addstr(0, 0, "Game Over. Press any key to exit.")
    stdscr.refresh()
    stdscr.getch()

def draw_puzzle_game(stdscr, board, puzzle_solution, cell_width=None, cell_height=None):
    """
    A puzzle loop that:
    - Draws the board
    - Asks the user to enter the next move in UCI format (e.g. 'd1a4')
    - Checks if it matches puzzle_solution in sequence
    - Automatically plays the puzzle's "opponent" move if it's next in puzzle_solution
    - Ends when puzzle_solution is exhausted or user enters an incorrect move
    """
    init_colors()
    # puzzle_solution is a list of moves in UCI format, e.g. ['d1a4','d8d7','a4e4']
    solution_index = 0

    # We'll keep going until we run out of solution moves
    while solution_index < len(puzzle_solution):
        height, width = stdscr.getmaxyx()
        if cell_width is None:
            cell_width = max(3, (width - 4) // 8)
        if cell_height is None:
            cell_height = max(3, (height - 4) // 8)

        prompt_y = draw_board_common(stdscr, board, cell_width, cell_height)
        if prompt_y < 0:
            return  # Board didn't fit

        next_move_uci = puzzle_solution[solution_index]
        next_move = chess.Move.from_uci(next_move_uci)
        
        # Check if it's the correct side to move for the next puzzle move.
        # If yes, prompt the user; if not, auto-play it.
        if board.turn == (board.color_at(next_move.from_square) == chess.WHITE):
            # Prompt user
            color_str = "White" if board.turn else "Black"
            stdscr.addstr(prompt_y, 0, f"Puzzle: Enter {color_str}'s move in UCI (e.g. {next_move_uci}):")
            stdscr.clrtoeol()
            stdscr.refresh()

            # Get user input
            stdscr.move(prompt_y + 1, 0)
            stdscr.clrtoeol()
            curses.echo()
            move_str = stdscr.getstr(prompt_y + 1, 0).decode('utf-8')
            curses.noecho()

            # Compare to puzzle_solution[solution_index]
            if move_str.strip().lower() == next_move_uci:
                # It's correct, so push it on the board
                board.push(next_move)
                solution_index += 1
            else:
                # Wrong!
                stdscr.addstr(prompt_y + 2, 0, 
                    f"Incorrect move. The puzzle solution expects {next_move_uci}. Press any key.")
                stdscr.refresh()
                stdscr.getch()
                return
        else:
            # Opponent move; auto-play it
            board.push(next_move)
            solution_index += 1

    # If we exit the loop, puzzle_solution is done => success
    draw_board_common(stdscr, board, cell_width, cell_height)
    stdscr.addstr(0, 0, "Puzzle solved! Press any key to exit.")
    stdscr.refresh()
    stdscr.getch()

def load_random_puzzle():
    """
    Fetch a random puzzle from lichess.org/api/puzzle/next,
    parse its PGN, and return the board set to puzzle's initial position
    plus the puzzle's solution in UCI list form.
    """
    url = "https://lichess.org/api/puzzle/next"
    response = requests.get(url, timeout=10)
    data = response.json()

    # Dump the entire JSON for debug purposes into "puzzle.json"
    with open("puzzle.json", "w") as f:
        json.dump(data, f, indent=2)

    puzzle_data = data["puzzle"]
    game_data = data["game"]

    puzzle_solution = puzzle_data["solution"]  # e.g. ["d1a4","d8d7","a4e4"]
    pgn = game_data["pgn"]                    # the PGN that leads up to puzzle
    initial_ply = puzzle_data["initialPly"]   # half-move index (1-based)

    # Parse the PGN with python-chess
    pgn_io = StringIO(pgn)
    game = chess.pgn.read_game(pgn_io)
    board = game.board()

    # The game.mainline_moves() is a generator of all moves.
    moves = list(game.mainline_moves())
    
    # Push exactly initial_ply - 1 moves (so that the puzzle starts at move #initialPly).
    # Also make sure we don't exceed the total length of the PGN.
    to_push = min(max(initial_ply - 1, 0), len(moves))
    for i in range(to_push):
        board.push(moves[i])

    return board, puzzle_solution

def main(pgn_file=None, puzzle_mode=False, cell_width=None, cell_height=None):
    """
    Main entry point. 
    - If puzzle_mode is True, fetch a puzzle, load it, and run puzzle UI.
    - Else if a pgn_file is provided, load the last position from that PGN.
    - Otherwise, start a fresh standard game.
    """
    if puzzle_mode:
        board, puzzle_solution = load_random_puzzle()
        curses.wrapper(draw_puzzle_game, board, puzzle_solution, cell_width, cell_height)
    else:
        if pgn_file:
            with open(pgn_file, 'r') as f:
                game = chess.pgn.read_game(f)
            board = game.board()
            for move in game.mainline_moves():
                board.push(move)
        else:
            board = chess.Board()
        curses.wrapper(draw_standard_game, board, cell_width, cell_height)


if __name__ == "__main__":
    import sys

    # Very simplistic command-line handling
    # e.g. "python puzzle_tui.py puzzle" to run puzzle mode
    # e.g. "python puzzle_tui.py mygame.pgn" to load a PGN
    if len(sys.argv) == 2 and sys.argv[1].lower() == "puzzle":
        main(puzzle_mode=True)
    elif len(sys.argv) == 2:
        main(pgn_file=sys.argv[1])
    else:
        main()

