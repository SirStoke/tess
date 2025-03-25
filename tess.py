#!/usr/bin/env python3
import curses
import chess
import chess.pgn
import requests
import json
from io import StringIO
import time # Import time for potential delays

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
    # Use default terminal colors for better compatibility maybe?
    # Let's stick with the original pairs for now.
    if curses.has_colors():
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_MAGENTA)  # Pink squares
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_YELLOW)   # Yellow squares
    # Fallback or default attributes if no colors
    global COLOR_PAIR_1, COLOR_PAIR_2
    COLOR_PAIR_1 = curses.color_pair(1) if curses.has_colors() else curses.A_NORMAL
    COLOR_PAIR_2 = curses.color_pair(2) if curses.has_colors() else curses.A_REVERSE


def draw_piece_ascii(stdscr, piece_char, x, y, cell_width, cell_height, bg_color):
    """
    Draws ASCII art for a given piece in a cell at (x, y).
    """
    shape = ASCII_PIECES.get(piece_char)
    if not shape:
        return
    shape_height = len(shape)
    shape_width = max(len(line) for line in shape)
    # Calculate offsets to center the shape within the cell
    offset_y = (cell_height - shape_height) // 2
    offset_x = (cell_width - shape_width) // 2
    # Ensure offsets are non-negative
    offset_y = max(0, offset_y)
    offset_x = max(0, offset_x)

    for row_idx, row_text in enumerate(shape):
        # Calculate target row and column on screen
        target_y = y + offset_y + row_idx
        target_x = x + offset_x
        # Ensure drawing stays within cell bounds and screen bounds
        if (y <= target_y < y + cell_height and
            0 <= target_y < curses.LINES - 1 and  # Avoid bottom right corner issues
            0 <= target_x < curses.COLS - 1):
            # Clip the text if it exceeds cell width
            available_width = cell_width - (target_x - x)
            clipped = row_text[:available_width]
            # Ensure clipped text doesn't exceed screen width
            if target_x + len(clipped) >= curses.COLS:
                clipped = clipped[:curses.COLS - 1 - target_x]

            if clipped: # Only draw if there's something to draw
                try:
                    stdscr.addstr(target_y, target_x, clipped, bg_color)
                except curses.error:
                    # Ignore errors typically caused by drawing at the very edge
                    pass


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
        # Try to display the error without crashing
        try:
            stdscr.addstr(0, 0, "Window too small to draw the chessboard.")
            stdscr.addstr(1, 0, f"Need HxW: {required_height}x{required_width}, Have: {height}x{width}")
            stdscr.refresh()
        except curses.error:
            pass # Ignore if window is *really* too small
        return -1

    # Draw squares
    for row in range(8):
        for col in range(8):
            x = col * cell_width + 3  # offset for file labels
            y = row * cell_height + 1 # offset for rank labels
            square_index = chess.square(col, 7 - row)
            piece = board.piece_at(square_index)
            # Checkerboard colors
            if (row + col) % 2 == 0:
                bg_color = COLOR_PAIR_2 # Yellow / Reversed
            else:
                bg_color = COLOR_PAIR_1 # Pink / Normal

            # Fill entire cell with background color
            for h_offset in range(cell_height):
                # Ensure drawing stays within screen bounds
                if y + h_offset < height -1 and x < width:
                    try:
                         # Draw spaces up to cell_width or edge of screen
                        line_len = min(cell_width, width - x -1)
                        if line_len > 0:
                            stdscr.addstr(y + h_offset, x, ' ' * line_len, bg_color)
                    except curses.error:
                         pass # Ignore drawing errors at edge

            # If there's a piece, draw it
            if piece:
                draw_piece_ascii(
                    stdscr, piece.symbol(),
                    x, y,
                    cell_width, cell_height,
                    bg_color
                )

    # Draw rank indicators on the left (8..1)
    rank_y_base = 1 + cell_height // 2 # Center vertically in the first row
    for row in range(8):
        target_y = row * cell_height + rank_y_base
        if 0 <= target_y < height -1:
             try:
                 stdscr.addstr(target_y, 1, str(8 - row))
             except curses.error:
                 pass

    # Draw file indicators (A..H) at the bottom
    file_x_base = 3 + cell_width // 2 # Center horizontally
    target_y = 8 * cell_height + 1 # Below the board
    if 0 <= target_y < height -1:
        for col in range(8):
            target_x = col * cell_width + file_x_base
            if 0 <= target_x < width -1:
                try:
                    stdscr.addstr(target_y, target_x, chr(ord('a') + col))
                except curses.error:
                    pass

    # Return a row for prompt usage
    prompt_y = 8 * cell_height + 2 # Adjusted slightly lower
    if prompt_y >= height - 2: # Ensure prompt lines fit
        prompt_y = height - 3
    if prompt_y < 0: prompt_y = 0 # Ensure non-negative

    return prompt_y

def draw_standard_game(stdscr, board, cell_width=None, cell_height=None):
    """
    Original TUI loop for a normal game.
    """
    init_colors()
    while not board.is_game_over():
        # Decide cell sizes if None
        height, width = stdscr.getmaxyx()
        cw = cell_width if cell_width is not None else max(3, (width - 4) // 8)
        ch = cell_height if cell_height is not None else max(3, (height - 4) // 8)

        prompt_y = draw_board_common(stdscr, board, cw, ch)
        if prompt_y < 0:
            stdscr.getch() # Wait for key press if window too small
            return

        # Prompt user
        color = "White" if board.turn else "Black"
        try:
            stdscr.addstr(prompt_y, 0, f"Enter {color}'s move (e.g., e4 or e2e4):")
            stdscr.clrtoeol()
            stdscr.refresh()
        except curses.error:
             # Ignore errors if prompt doesn't fit fully
             pass

        # Get user move
        move_input_y = min(prompt_y + 1, height - 1)
        stdscr.move(move_input_y, 0)
        stdscr.clrtoeol()
        curses.echo()
        try:
            # Limit input length slightly less than screen width
            input_str_bytes = stdscr.getstr(move_input_y, 0, min(width - 2, 20))
            move_str = input_str_bytes.decode('utf-8').strip()
        except curses.error:
            move_str = "" # Handle potential errors during input
        curses.noecho()

        # Try parse SAN or UCI
        move = None
        try:
            move = board.parse_san(move_str)
        except ValueError:
            try:
                move = board.parse_uci(move_str)
            except ValueError:
                try:
                    # Add message line - ensure it fits
                    msg_y = min(prompt_y + 2, height - 1)
                    stdscr.move(msg_y, 0)
                    stdscr.clrtoeol()
                    stdscr.addstr(msg_y, 0, "Invalid move format. Press any key.")
                    stdscr.refresh()
                    stdscr.getch()
                except curses.error:
                    pass # Ignore if message doesn't fit
                continue # Ask for input again

        if move in board.legal_moves:
            board.push(move)
        else:
            try:
                msg_y = min(prompt_y + 2, height - 1)
                stdscr.move(msg_y, 0)
                stdscr.clrtoeol()
                stdscr.addstr(msg_y, 0, "Illegal move. Press any key.")
                stdscr.refresh()
                stdscr.getch()
            except curses.error:
                 pass # Ignore if message doesn't fit


    # Game over
    height, _ = stdscr.getmaxyx()
    prompt_y = draw_board_common(stdscr, board, cw, ch) # Redraw final position
    if prompt_y >=0:
        msg_y = min(prompt_y, height -1)
        try:
             stdscr.move(msg_y, 0)
             stdscr.clrtoeol()
             stdscr.addstr(msg_y, 0, f"Game Over: {board.result()}. Press any key to exit.")
             stdscr.refresh()
             stdscr.getch()
        except curses.error:
             pass # Ignore if message doesn't fit

def draw_puzzle_game(stdscr, board, puzzle_solution, cell_width=None, cell_height=None):
    """
    A puzzle loop that alternates user moves and opponent moves from puzzle_solution.
    """
    init_colors()
    solution_index = 0

    while solution_index < len(puzzle_solution):
        height, width = stdscr.getmaxyx()
        cw = cell_width if cell_width is not None else max(3, (width - 4) // 8)
        ch = cell_height if cell_height is not None else max(3, (height - 4) // 8)

        prompt_y = draw_board_common(stdscr, board, cw, ch)
        if prompt_y < 0:
            stdscr.getch() # Wait for key press if window too small
            return

        next_move_uci = puzzle_solution[solution_index]

        # Determine if it's the user's turn based on index (0, 2, ... are user)
        is_user_turn = (solution_index % 2 == 0)

        # Validate the expected puzzle move *before* asking user or auto-playing
        try:
            expected_move = board.parse_uci(next_move_uci)
        except ValueError as e:
            # This indicates an issue with the puzzle data or the board state setup
            try:
                msg_y = min(prompt_y + 2, height - 1)
                stdscr.move(msg_y, 0)
                stdscr.clrtoeol()
                stdscr.addstr(msg_y, 0, f"Error: Puzzle move '{next_move_uci}' is invalid/illegal: {e}")
                stdscr.addstr(msg_y+1, 0, f"FEN: {board.fen()}. Press key.")
                stdscr.refresh()
                stdscr.getch()
            except curses.error: pass
            return # Exit if puzzle data is broken

        if is_user_turn:
            # Prompt user
            color_str = "White" if board.turn else "Black"
            try:
                stdscr.addstr(prompt_y, 0, f"Puzzle: Enter {color_str}'s move in UCI (e.g. {next_move_uci}):")
                stdscr.clrtoeol()
                stdscr.refresh()
            except curses.error: pass

            # Get user input
            input_y = min(prompt_y + 1, height - 1)
            stdscr.move(input_y, 0)
            stdscr.clrtoeol()
            curses.echo()
            try:
                input_bytes = stdscr.getstr(input_y, 0, min(width - 2, 10))
                move_str = input_bytes.decode('utf-8').strip().lower()
            except curses.error:
                move_str = ""
            curses.noecho()

            # Compare user input to the expected puzzle move
            if move_str == next_move_uci:
                # Correct move
                board.push(expected_move)
                solution_index += 1
            else:
                # Incorrect move
                try:
                    msg_y = min(prompt_y + 2, height - 1)
                    stdscr.move(msg_y, 0)
                    stdscr.clrtoeol()
                    stdscr.addstr(msg_y, 0, f"Incorrect. Expected: {next_move_uci}. You entered: {move_str}. Press key.")
                    stdscr.refresh()
                    stdscr.getch()
                except curses.error: pass
                return # End puzzle attempt
        else:
            # Opponent's turn: auto-play the move
            board.push(expected_move)
            solution_index += 1

            # Optional: Show opponent move and pause before next user prompt
            prompt_y = draw_board_common(stdscr, board, cw, ch) # Redraw board *after* opponent moves
            if prompt_y >= 0:
                try:
                    stdscr.addstr(prompt_y, 0, f"Opponent plays: {next_move_uci}. Press any key...")
                    stdscr.clrtoeol()
                    stdscr.refresh()
                    stdscr.getch() # Wait for user acknowledgement
                except curses.error: pass
            else:
                 # If redraw failed (e.g., resize), just proceed
                 time.sleep(0.5) # Small delay


    # If loop finishes, puzzle solved successfully
    height, _ = stdscr.getmaxyx()
    prompt_y = draw_board_common(stdscr, board, cw, ch) # Draw final board
    if prompt_y >= 0:
        try:
             msg_y = min(prompt_y + 2, height - 1)
             stdscr.move(msg_y, 0)
             stdscr.clrtoeol()
             stdscr.addstr(msg_y, 0, "Puzzle solved! Press any key to exit.")
             stdscr.refresh()
             stdscr.getch()
        except curses.error: pass


def load_random_puzzle():
    """
    Fetch a random puzzle from lichess.org/api/puzzle/next,
    parse its PGN, and return the board set to puzzle's initial position
    plus the puzzle's solution in UCI list form.
    """
    # Lichess daily puzzle endpoint - tends to be more consistent?
    # url = "https://lichess.org/api/puzzle/daily"
    # Let's stick to /next for randomness as requested originally
    url = "https://lichess.org/api/puzzle/next"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching puzzle from Lichess: {e}")
        return None, None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response from Lichess: {e}")
        print(f"Response text: {response.text[:200]}...") # Show beginning of response
        return None, None


    # Dump the entire JSON for debug purposes into "puzzle.json"
    try:
        with open("puzzle.json", "w") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        print(f"Warning: Could not write puzzle.json: {e}")


    try:
        puzzle_data = data["puzzle"]
        game_data = data["game"]

        puzzle_solution = puzzle_data["solution"]  # e.g. ["d1a4","d8d7","a4e4"]
        pgn = game_data["pgn"]                    # the PGN that leads up to puzzle
        initial_ply = puzzle_data["initialPly"]   # half-move index (0-based in some contexts, 1-based in others - Lichess API doc implies it's number of ply *played*)
                                                  # python-chess board.ply() is 0-based. A board after 1.e4 has ply=1.
                                                  # If initialPly is the number of half-moves *before* the puzzle starts, we need to push that many moves.

    except KeyError as e:
        print(f"Error: Missing expected key {e} in Lichess puzzle data.")
        return None, None

    # Parse the PGN with python-chess
    pgn_io = StringIO(pgn)
    game = chess.pgn.read_game(pgn_io)
    if game is None:
        print("Error: Failed to parse PGN from Lichess puzzle.")
        return None, None

    board = game.board()

    # The game.mainline_moves() is a generator of all moves.
    moves = list(game.mainline_moves())

    # Let's assume initialPly is the number of ply *completed* before the puzzle position.
    # So we need to push exactly initialPly moves.
    # Check against example: if initialPly=0, puzzle starts from initial pos, push 0 moves.
    # If initialPly=1 (after 1. e4), puzzle starts after e4, push 1 move. Looks correct.
    to_push = min(max(initial_ply, 0), len(moves)) # Ensure ply is non-negative and within PGN bounds

    try:
        for i in range(to_push):
            board.push(moves[i])
    except (AssertionError, ValueError) as e:
         print(f"Error applying PGN moves to board: {e}")
         print(f"Failed at move index {i}, move {moves[i].uci() if i < len(moves) else 'N/A'}")
         print(f"PGN: {pgn}")
         print(f"Initial Ply: {initial_ply}")
         return None, None


    # Sanity Check: After setting up the board, the *next* move should correspond
    # to the player whose turn it is. The *first* move of the puzzle solution
    # must be playable by the player whose turn it is on the board.
    if not puzzle_solution:
        print("Error: Puzzle solution is empty.")
        return None, None

    first_puzzle_move_uci = puzzle_solution[0]
    try:
        # Check if the first move is legal in the starting position.
        # This helps catch mismatches between initialPly and the actual puzzle start.
        board.parse_uci(first_puzzle_move_uci)
    except ValueError:
        # If the first move isn't legal, maybe initialPly definition was off by one?
        # Try pushing one *less* move from the PGN.
        print(f"Warning: First puzzle move {first_puzzle_move_uci} illegal after {initial_ply} ply. Trying {initial_ply - 1} ply.")
        board = game.board() # Reset board
        to_push = min(max(initial_ply - 1, 0), len(moves))
        try:
            for i in range(to_push):
                board.push(moves[i])
            # Re-check if first puzzle move is now legal
            board.parse_uci(first_puzzle_move_uci)
            print(f"Success: First puzzle move now legal after {initial_ply - 1} ply.")
        except (ValueError, AssertionError) as e2:
            # If still fails, the puzzle data might be genuinely inconsistent.
            print(f"Error: Cannot reconcile initialPly ({initial_ply}) and first puzzle move ({first_puzzle_move_uci}).")
            print(f"Board FEN after {to_push} ply: {board.fen()}")
            print(f"Error during check: {e2}")
            return None, None # Give up if inconsistent


    return board, puzzle_solution

def main(pgn_file=None, puzzle_mode=False, cell_width=None, cell_height=None):
    """
    Main entry point.
    - If puzzle_mode is True, fetch a puzzle, load it, and run puzzle UI.
    - Else if a pgn_file is provided, load the last position from that PGN.
    - Otherwise, start a fresh standard game.
    """
    board = None
    puzzle_solution = None

    if puzzle_mode:
        print("Fetching random Lichess puzzle...")
        board, puzzle_solution = load_random_puzzle()
        if board is None or puzzle_solution is None:
            print("Failed to load puzzle. Exiting.")
            return # Exit if puzzle loading failed
        print("Puzzle loaded. Starting TUI...")
        time.sleep(1) # Give user time to read messages
        curses.wrapper(draw_puzzle_game, board, puzzle_solution, cell_width, cell_height)
    else:
        if pgn_file:
            try:
                with open(pgn_file, 'r') as f:
                    game = chess.pgn.read_game(f)
                if game is None:
                    print(f"Error: Could not parse PGN file: {pgn_file}")
                    return
                board = game.board()
                for move in game.mainline_moves():
                    board.push(move)
            except FileNotFoundError:
                print(f"Error: PGN file not found: {pgn_file}")
                return
            except Exception as e:
                 print(f"Error loading PGN file {pgn_file}: {e}")
                 return
        else:
            board = chess.Board()
        curses.wrapper(draw_standard_game, board, cell_width, cell_height)


if __name__ == "__main__":
    import sys

    # Very simplistic command-line handling
    # e.g. "python tess.py puzzle" to run puzzle mode
    # e.g. "python tess.py mygame.pgn" to load a PGN
    if len(sys.argv) == 2 and sys.argv[1].lower() == "puzzle":
        main(puzzle_mode=True)
    elif len(sys.argv) == 2:
        # Check if it's a pgn file or just "puzzle"
        if sys.argv[1].lower().endswith(".pgn"):
            main(pgn_file=sys.argv[1])
        else:
             print(f"Unrecognized argument: {sys.argv[1]}")
             print("Usage: python tess.py [puzzle | <filename.pgn>]")
    else:
        main()
