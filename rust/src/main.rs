use crossterm::event::{self, Event, KeyCode, KeyEvent};
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use pgn_reader::{RawHeader, SanPlus, Skip, Visitor};
use ratatui::text::Line;
use ratatui::{
    backend::{Backend, CrosstermBackend},
    layout::{Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    text::Span,
    widgets::{Block, Paragraph},
    Terminal,
};
use serde::Deserialize;
use shakmaty::fen::Fen;
use shakmaty::{
    san, CastlingMode, Chess, Color as ChessColor, File, Move, Position, Rank, Role, Square,
};
use std::{collections::HashMap, io, time::Duration, time::Instant};

// ----------------------------------------------
// Piece ASCII definitions, similar to Python version
// ----------------------------------------------
static ASCII_PIECES: &[(&str, &[&str])] = &[
    ("P", &[" ^ ", "(P)", "/_\\"]),
    ("N", &[" __", "/ N", "\\_/"]),
    ("B", &["  ^", " /B\\", " \\_/"]),
    ("R", &["[R]", "[R]", "[R]"]),
    ("Q", &[" Q ", "( )", " \\|"]),
    ("K", &[" K ", "(. )", " | "]),
    ("p", &[" ^ ", "(p)", "/_\\"]),
    ("n", &[" __", "/ n", "\\_/"]),
    ("b", &["  ^", " /b\\", " \\_/"]),
    ("r", &["[r]", "[r]", "[r]"]),
    ("q", &[" q ", "( )", " \\|"]),
    ("k", &[" k ", "(. )", " | "]),
];

fn piece_ascii_map() -> HashMap<char, Vec<String>> {
    let mut map = HashMap::new();
    for (symbol, lines) in ASCII_PIECES {
        map.insert(
            symbol.chars().next().unwrap(),
            lines.iter().map(|s| s.to_string()).collect(),
        );
    }
    map
}

// ----------------------------------------------
// Lichess puzzle JSON structure for `lichess.org/api/puzzle/next`
// ----------------------------------------------
#[derive(Debug, Deserialize)]
struct LichessNextPuzzle {
    puzzle: Puzzle,
    game: Game,
}

#[derive(Debug, Deserialize)]
struct Puzzle {
    solution: Vec<String>,
    initialPly: u16,
}

#[derive(Debug, Deserialize)]
struct Game {
    pgn: String,
}

// ----------------------------------------------
// Application modes
// ----------------------------------------------
#[derive(Clone)]
enum AppMode {
    StandardGame,
    Puzzle {
        solution: Vec<Move>,
        solution_index: usize,
    },
}

// ----------------------------------------------
// Application state
// ----------------------------------------------

struct App {
    board: Chess,
    mode: AppMode,
    input_buffer: String,
    message: String,
    cell_width: usize,
    cell_height: usize,
}

impl App {
    fn new_standard(board: Chess) -> Self {
        Self {
            board,
            mode: AppMode::StandardGame,
            input_buffer: String::new(),
            message: String::new(),
            cell_width: 5,
            cell_height: 3,
        }
    }

    fn new_puzzle(board: Chess, solution: Vec<Move>) -> Self {
        Self {
            board,
            mode: AppMode::Puzzle {
                solution,
                solution_index: 0,
            },
            input_buffer: String::new(),
            message: String::from("Puzzle mode: please enter moves in UCI (e.g. e2e4)."),
            cell_width: 5,
            cell_height: 3,
        }
    }
}

// ----------------------------------------------
// Main entry
// ----------------------------------------------
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();

    // Basic command handling
    let mut app = if args.len() == 2 && args[1].to_lowercase() == "puzzle" {
        // puzzle mode
        let (board, solution) = load_random_puzzle()?;
        App::new_puzzle(board, solution)
    } else if args.len() == 2 {
        // load PGN file
        let filename = &args[1];
        let board = load_pgn_position(filename)?;
        App::new_standard(board)
    } else {
        // fresh standard game
        App::new_standard(Chess::default())
    };

    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    crossterm::execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // Run the main loop
    let res = run_app(&mut terminal, &mut app);

    // Cleanup
    disable_raw_mode()?;
    crossterm::execute!(terminal.backend_mut(), LeaveAlternateScreen,)?;
    terminal.show_cursor()?;

    if let Err(err) = res {
        eprintln!("Error: {:?}", err);
    }

    Ok(())
}

// ----------------------------------------------
// The core event loop
// ----------------------------------------------
fn run_app<B: Backend>(terminal: &mut Terminal<B>, app: &mut App) -> io::Result<()> {
    let mut last_tick = Instant::now();
    let tick_rate = Duration::from_millis(250);

    loop {
        // Draw
        terminal.draw(|f| ui(f, app))?;

        // Handle input, non-blocking
        let timeout = tick_rate
            .checked_sub(last_tick.elapsed())
            .unwrap_or_else(|| Duration::from_secs(0));

        if crossterm::event::poll(timeout)? {
            if let Event::Key(key) = event::read()? {
                if !handle_key_event(app, key) {
                    // false => exit signal
                    return Ok(());
                }
            }
        }

        // on_tick if needed
        if last_tick.elapsed() >= tick_rate {
            last_tick = Instant::now();
        }
    }
}

// ----------------------------------------------
// Draw the UI with ratatui
// ----------------------------------------------
fn ui(f: &mut ratatui::Frame, app: &App) {
    // Layout: top for board, bottom for user input / messages
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length((8 * app.cell_height + 2) as u16), // board area
            Constraint::Min(3),                                   // input area
        ])
        .split(f.area());

    // 1) Render the chessboard as a Paragraph of styled text
    let board_lines = make_board_text(app);
    let board_paragraph = Paragraph::new(board_lines).block(Block::default());
    f.render_widget(board_paragraph, chunks[0]);

    let input_paragraph =
        Paragraph::new(format!("{}\nMove input: {}", app.message, app.input_buffer));
    f.render_widget(input_paragraph, chunks[1]);
}

// ----------------------------------------------
// Build the board ASCII with styling
// ----------------------------------------------
fn make_board_text(app: &App) -> Vec<Line> {
    // We'll build a 2D buffer of styled chars
    let board_width = 8 * app.cell_width;
    let board_height = 8 * app.cell_height;

    let pink_style = Style::default().fg(Color::White).bg(Color::Magenta);
    let yellow_style = Style::default().fg(Color::Black).bg(Color::Yellow);

    // Prepare piece ASCII map
    let ascii_map = piece_ascii_map();

    // We'll create a 2D array of (char, Style).
    let mut buffer: Vec<Vec<(char, Style)>> =
        vec![vec![(' ', Style::default()); board_width]; board_height];

    // Fill squares
    for row in 0..8 {
        for col in 0..8 {
            // top-left corner of this cell in the buffer
            let cell_x = col * app.cell_width;
            let cell_y = row * app.cell_height;

            // color
            let style = if (row + col) % 2 == 0 {
                // "light" square => yellow
                yellow_style
            } else {
                pink_style
            };

            // fill with spaces
            for dy in 0..app.cell_height {
                for dx in 0..app.cell_width {
                    if cell_y + dy < board_height && cell_x + dx < board_width {
                        buffer[cell_y + dy][cell_x + dx] = (' ', style);
                    }
                }
            }

            // place piece ASCII if any
            let sq =
                shakmaty::Square::from_coords(File::new(col as u32), Rank::new((7 - row) as u32));

            if let Some(piece) = app.board.board().piece_at(sq) {
                let symbol_char = piece_char(piece);
                if let Some(shape_lines) = ascii_map.get(&symbol_char) {
                    let shape_height = shape_lines.len();
                    let shape_width = shape_lines.iter().map(|l| l.len()).max().unwrap_or(0);

                    let offset_y = (app.cell_height.saturating_sub(shape_height)) / 2;
                    let offset_x = (app.cell_width.saturating_sub(shape_width)) / 2;

                    for (sy, line) in shape_lines.iter().enumerate() {
                        let ty = cell_y + offset_y + sy;
                        if ty >= board_height {
                            break;
                        }
                        let mut tx = cell_x + offset_x;
                        for ch in line.chars() {
                            if tx >= board_width {
                                break;
                            }
                            buffer[ty][tx] = (ch, style);
                            tx += 1;
                        }
                    }
                }
            }
        }
    }

    // Now we also want rank and file indicators (like Python code).
    // For simplicity, let's place them left of each rank, and below each file.

    // Ranks on left: row => (8-row)
    for row in 0..8 {
        let label = format!("{}", 8 - row);
        // place at x=0, y = row*cell_height
        // we only place it if there's space
        let py = row * app.cell_height;
        for (i, ch) in label.chars().enumerate() {
            if i < board_width {
                buffer[py][i].0 = ch;
                buffer[py][i].1 = Style::default().fg(Color::White).bg(Color::Reset);
            }
        }
    }

    // Files on bottom: col => A..H
    let file_labels = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];
    let bottom_y = board_height.saturating_sub(1);
    for col in 0..8 {
        let ch = file_labels[col];
        let px = col * app.cell_width;
        if px < board_width {
            buffer[bottom_y][px].0 = ch;
            buffer[bottom_y][px].1 = Style::default().fg(Color::White).bg(Color::Reset);
        }
    }

    // Convert 2D buffer into Vec<Line>
    buffer
        .into_iter()
        .map(|row_vec| {
            let mut spans: Vec<Span> = Vec::with_capacity(row_vec.len());
            // We can group consecutive (char, style) that have the same style
            let mut current_style = row_vec[0].1;
            let mut current_text = String::new();

            for &(ch, st) in &row_vec {
                if st == current_style {
                    current_text.push(ch);
                } else {
                    // flush
                    spans.push(Span::styled(current_text, current_style));
                    // start new group
                    current_text = ch.to_string();
                    current_style = st;
                }
            }
            // flush last group
            spans.push(Span::styled(current_text, current_style));
            Line::from(spans)
        })
        .collect()
}

// Convert a shakmaty piece into a single ASCII letter for ASCII_PIECES map
fn piece_char(piece: shakmaty::Piece) -> char {
    let ch = match piece.role {
        Role::Pawn => 'P',
        Role::Knight => 'N',
        Role::Bishop => 'B',
        Role::Rook => 'R',
        Role::Queen => 'Q',
        Role::King => 'K',
    };
    if piece.color == ChessColor::Black {
        ch.to_ascii_lowercase()
    } else {
        ch
    }
}

// ----------------------------------------------
// Handle keyboard events (for move input, etc.)
// Return false if we should quit
// ----------------------------------------------
fn handle_key_event(app: &mut App, key: KeyEvent) -> bool {
    match key.code {
        KeyCode::Char('q') => {
            // Quit on 'q'
            return false;
        }
        KeyCode::Enter => {
            // User pressed Enter => parse the input as a move
            let input = app.input_buffer.clone();
            if !input.is_empty() {
                match app.mode.clone() {
                    AppMode::StandardGame => handle_standard_move(app, input.trim()),
                    AppMode::Puzzle {
                        solution,
                        solution_index,
                    } => {
                        handle_puzzle_move(app, input.trim(), &solution, &solution_index);
                    }
                }
            }
            app.input_buffer.clear();
        }
        KeyCode::Backspace => {
            app.input_buffer.pop();
        }
        KeyCode::Char(c) => {
            app.input_buffer.push(c);
        }
        _ => {}
    }

    true
}

// Handle moves for standard game mode
fn handle_standard_move(app: &mut App, input: &str) {
    // Try parse as SAN first
    let parse_result = san::San::from_ascii(input.as_bytes());
    if let Ok(san_move) = parse_result {
        if let Ok(mv) = san_move.to_move(&app.board) {
            // Check if legal
            if app.board.is_legal(&mv) {
                app.board = app.board.clone().play(&mv).unwrap();
                app.message = format!("Move {} played", input);
                if app.board.is_game_over() {
                    app.message = format!("Game over. {:?}", app.board.outcome());
                }
                return;
            }
        }
    }
    app.message = format!("Illegal or unrecognized move: {}", input);
}

// Handle puzzle logic
fn handle_puzzle_move(
    app: &mut App,
    input: &str,
    solution: &Vec<Move>,
    solution_index: &usize,
) -> usize {
    let mut new_index = solution_index.clone();
    // If puzzle is solved, do nothing
    if new_index >= solution.len() {
        app.message = "Puzzle already solved.".to_string();
        return new_index;
    }
    let expected_move = &solution[new_index];

    // Try parse the user input as a UCI move
    let maybe_move = parse_uci_move(&app.board, input);
    match maybe_move {
        Some(user_move) if user_move.eq(expected_move) => {
            // correct
            app.board = app.board.clone().play(&user_move).unwrap();
            new_index += 1;
            app.message = format!("Correct! Move {} was played.", input);

            // If there's an immediate next move from puzzle that belongs to "opponent", auto-play it
            while new_index < solution.len() {
                let next: &Move = &solution[new_index];
                let color_of_next =
                    if let Some(pc) = app.board.board().piece_at(next.from().unwrap()) {
                        pc.color
                    } else {
                        // If we can't deduce piece color, break
                        break;
                    };
                // If it's the same side as currently on move, break
                // Otherwise, auto-play
                let side_to_move = app.board.turn();
                if side_to_move == color_of_next {
                    // The puzzle expects a user move next
                    break;
                } else {
                    // It's the "opponent" move, so auto-play
                    app.board = app.board.clone().play(&next).unwrap();
                    new_index += 1;
                }
            }

            // Check if puzzle finished
            if new_index >= solution.len() {
                app.message = "Puzzle solved! Congratulations.".to_string();
            }
        }
        _ => {
            app.message = format!(
                "Incorrect move. Expected UCI: {}. Puzzle failed.",
                move_to_uci(expected_move)
            );
            // You might choose to end puzzle mode or just keep going
            // We'll just end it by bumping index
            new_index = solution.len();
        }
    }
    new_index
}

// ----------------------------------------------
// Utility: parse user input as UCI in the current position
// ----------------------------------------------
fn parse_uci_move(board: &Chess, input: &str) -> Option<Move> {
    let all_moves = board.legal_moves();
    for m in all_moves {
        let uci_str = move_to_uci(&m);
        if uci_str == input.to_lowercase() {
            return Some(m);
        }
    }
    None
}

// Convert Move to "e2e4" style string
fn move_to_uci(mv: &Move) -> String {
    mv.to_string() // shakmaty uses UCI by default
}

struct LastPosition {
    pos: Chess,
    moves: usize,
    max_ply: Option<usize>,
}

impl LastPosition {
    fn new(max_ply: Option<usize>) -> LastPosition {
        LastPosition {
            pos: Chess::default(),
            moves: 0,
            max_ply,
        }
    }
}

impl Visitor for LastPosition {
    type Result = Chess;

    fn header(&mut self, key: &[u8], value: RawHeader<'_>) {
        // Support games from a non-standard starting position.
        if key == b"FEN" {
            let pos = Fen::from_ascii(value.as_bytes())
                .ok()
                .and_then(|f| f.into_position(CastlingMode::Standard).ok());

            if let Some(pos) = pos {
                self.pos = pos;
            }
        }
    }

    fn begin_variation(&mut self) -> Skip {
        Skip(true) // stay in the mainline
    }

    fn san(&mut self, san_plus: SanPlus) {
        match self.max_ply {
            Some(max) if self.moves < max => {
                if let Ok(m) = san_plus.san.to_move(&self.pos) {
                    self.pos.play_unchecked(&m);
                    self.moves += 1
                }
            }
            _ => {}
        }
    }

    fn end_game(&mut self) -> Self::Result {
        ::std::mem::replace(&mut self.pos, Chess::default())
    }
}

// ----------------------------------------------
// Load random puzzle from lichess
// ----------------------------------------------
fn load_random_puzzle() -> anyhow::Result<(Chess, Vec<Move>)> {
    let url = "https://lichess.org/api/puzzle/next";
    let resp: LichessNextPuzzle = reqwest::blocking::get(url)?.json()?;

    // Parse puzzle solution as UCI moves
    let puzzle_solution_uci = resp.puzzle.solution;
    // Parse the PGN
    let pgn = resp.game.pgn;
    let initial_ply = resp.puzzle.initialPly as usize;
    let puzzle_game = parse_game(&pgn, Some(initial_ply))?;

    // Now parse puzzle_solution_uci
    let mut solution_moves = Vec::new();
    for uci_str in puzzle_solution_uci {
        // Attempt to find a matching legal move
        let all_legals = puzzle_game.legal_moves();
        let found = all_legals.into_iter().find(|m| move_to_uci(&m) == uci_str);
        if let Some(mv) = found {
            solution_moves.push(mv);
        } else {
            // Possibly an invalid puzzle? We'll just skip or break
            break;
        }
    }

    Ok((puzzle_game, solution_moves))
}

// ----------------------------------------------
// Load a PGN from file and return final position
// ----------------------------------------------
fn load_pgn_position(path: &str) -> anyhow::Result<Chess> {
    let text = std::fs::read_to_string(path)?;
    parse_game(&text, None)
}

fn parse_game(pgn: &str, inital_ply: Option<usize>) -> anyhow::Result<Chess> {
    let mut game_pos = LastPosition::new(inital_ply);
    // Use pgn-reader to parse the PGN
    let mut reader = pgn_reader::BufferedReader::new(pgn.as_bytes());
    let parsed_game: Chess = reader
        .read_game(&mut game_pos)?
        .ok_or(anyhow::anyhow!("unable to read game"))?;
    Ok(parsed_game)
}
