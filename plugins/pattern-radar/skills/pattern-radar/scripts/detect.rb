#!/usr/bin/env ruby
# frozen_string_literal: true

# pattern-radar のシグナル検出スクリプト。
#
# 数えられる事実だけを JSON Lines で出力する。パターン名は出力しない（判定は SKILL.md 側の責任）。
# 正規表現ベースのヒューリスティックであり、完全性より誤検出の少なさを優先する。
# 依存は Ruby 標準ライブラリのみ。
#
# 使い方:
#   ruby detect.rb app/controllers/orders_controller.rb src/components/Foo.tsx
#   ruby detect.rb app/                # ディレクトリは再帰的に展開する
#   ruby detect.rb --diff              # 未ステージ＋ステージ済み＋未追跡を対象にする
#   ruby detect.rb --diff main         # main...HEAD の差分を対象にする

require "json"
require "open3"
require "ripper"
require "set"

# 閾値。ここだけを変更すれば検出の強さを調整できる。
# すべて「この値以上で報告する」という意味に統一している（閾値未満は出力しない）。
THRESHOLDS = {
  controller_action_lines: 21,      # controller の1アクションが20行超（=21行以上）
  persistence_calls_per_method: 2,  # 1メソッド内の save/save!/update/update!/create! の回数
  case_when_branches: 3,            # 1つの case に属する when 節の数
  nil_checks_per_receiver: 3,       # 同一レシーバへの nil?/present?/blank? の出現回数
  validates_with_context: 1,        # validates ... on: の出現
  callback_block_lines: 5,          # after_commit/after_save のブロック行数
  use_state_per_component: 3,       # 1コンポーネントあたりの useState 呼び出し数
  prop_passthrough_components: 3    # 受け取った同名 prop をそのまま子へ渡しているコンポーネントの数
}.freeze

# シグナルと軸の対応。複数軸にまたがるものは "F/D" のようにスラッシュ区切りで返す。
AXES = {
  controller_action_lines: "D",
  persistence_calls_per_method: "F/D",
  case_when_branches: "A",
  nil_checks_per_receiver: "A",
  validates_with_context: "F",
  callback_block_lines: "H",
  use_state_per_component: "J",
  prop_passthrough_components: "J"
}.freeze

RUBY_EXTS = %w[.rb].freeze
TSX_EXTS = %w[.tsx .jsx].freeze
TARGET_EXTS = (RUBY_EXTS + TSX_EXTS + %w[.ts]).freeze

MAX_FILE_BYTES = 512 * 1024                                  # これより大きいファイルは読まない
SKIP_DIRS = %w[.git node_modules vendor tmp log coverage dist build .next].freeze

# --- 出力 ---------------------------------------------------------------

def emit(file:, line:, signal:, count:)
  threshold = THRESHOLDS.fetch(signal)
  return if count < threshold

  puts JSON.generate(
    "file" => file,
    "line" => line,
    "signal" => signal.to_s,
    "count" => count,
    "threshold" => threshold,
    "axis" => AXES.fetch(signal)
  )
end

# --- 対象ファイルの決定 -------------------------------------------------

# git はすべて配列形式で起動する（シェルを経由しないので base に何が入っても展開されない）
def git(*args)
  out, status = Open3.capture2e("git", *args)
  status.success? ? out : ""
end

# -z 付きで取得し NUL で分割する（改行や空白を含むファイル名、core.quotePath の引用を避けるため）
def git_paths(*args)
  git(*args, "-z").split("\0").reject(&:empty?)
end

def diff_files(base = nil)
  if base
    # ブランチ全体のレビュー。実在するリビジョンかを先に検証し、解決できなければ空で返す
    if git("rev-parse", "--verify", "--quiet", "#{base}^{commit}").empty?
      warn "base '#{base}' をリビジョンとして解決できません"
      return []
    end

    git_paths("diff", "--name-only", "#{base}...HEAD")
  else
    # 既定は「まだコミットしていない変更すべて」。
    # 未ステージ・ステージ済み・未追跡の3種を合わせる（staged 済みや新規ファイルを取りこぼさないため）
    (git_paths("diff", "--name-only") +
      git_paths("diff", "--name-only", "--cached") +
      git_paths("ls-files", "--others", "--exclude-standard")).uniq
  end
end

def skip_dir?(path)
  path.split(File::SEPARATOR).any? { |part| SKIP_DIRS.include?(part) }
end

# 対象になる通常ファイルか。シンボリックリンクは辿らない（リンク経由で対象外へ出ないため）
def analyzable?(path)
  return false unless TARGET_EXTS.include?(File.extname(path))
  return false if File.symlink?(path) || !File.file?(path)

  if File.size(path) > MAX_FILE_BYTES
    warn "skip #{path}: #{MAX_FILE_BYTES} バイトを超えるため対象外"
    return false
  end

  true
end

# 明示的に渡されたファイルは常に対象。SKIP_DIRS はディレクトリ展開の中だけに効かせる
# （引数の祖先に tmp/ などが含まれていても、その配下を丸ごと捨てない）
def expand_targets(args)
  args.flat_map { |arg|
    next [arg] unless File.directory?(arg)

    root = %r{\A#{Regexp.escape(arg.chomp("/"))}/}
    Dir.glob(File.join(arg, "**", "*")).reject { |path| skip_dir?(path.sub(root, "")) }
  }.select { |path| analyzable?(path) }.uniq
end

# --- 共通ユーティリティ -------------------------------------------------

def code_line_count(lines)
  lines.count { |line| !line.strip.empty? }
end

# start_index の行と同じインデントの end を探す。見つからなければ nil。
def block_end_index(lines, start_index, indent)
  pattern = /^#{Regexp.escape(indent)}end\b/
  ((start_index + 1)...lines.size).each do |i|
    return i if lines[i] =~ pattern
  end
  nil
end

def endless_def?(line)
  line.match?(/^\s*def\s+[\w.:?!\[\]=<>+\-*\/]+(\([^)]*\))?\s*=\s*[^=]/)
end

# --- Ruby の検出 --------------------------------------------------------

PERSISTENCE_CALL = /(?<![\w:])(?:save!|save|update!|update|create!)(?![\w!])/
NIL_CHECK = /([@$]?[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\.(?:nil\?|present\?|blank\?)/
VALIDATES_WITH_CONTEXT = /\bvalidates?\b.*\bon:\s*(?::\w+|%i\[|\[)/

# コメント・文字列リテラルの中身を字句解析で落とす（"save" や # save を呼び出しと数えないため）。
# 行番号とインデントは保つ。解析に失敗したら元の行をそのまま返す。
def scrub_ruby(raw_lines)
  dropped = %i[on_comment on_embdoc on_embdoc_beg on_embdoc_end on_tstring_content on_words_sep]
  buffers = Array.new(raw_lines.size) { +"" }

  Ripper.lex(raw_lines.join).each do |(lineno, _col), type, token|
    index = lineno - 1
    next if index.negative? || index >= buffers.size
    next if dropped.include?(type)

    buffers[index] << token.delete("\n")
  end

  buffers.map { |line| "#{line}\n" }
rescue StandardError
  raw_lines
end

def controller?(path)
  path.include?("app/controllers") || File.basename(path).end_with?("_controller.rb")
end

def analyze_ruby(path, raw_lines)
  lines = scrub_ruby(raw_lines)
  private_from = lines.index { |line| line.match?(/^\s*(private|protected)\s*$/) } || lines.size

  each_method(lines) do |_name, start_index, end_index|
    body = lines[(start_index + 1)...end_index]

    if controller?(path) && start_index < private_from
      emit(file: path, line: start_index + 1, signal: :controller_action_lines,
           count: code_line_count(body))
    end

    calls = body.join.scan(PERSISTENCE_CALL).size
    emit(file: path, line: start_index + 1, signal: :persistence_calls_per_method, count: calls)
  end

  detect_case_branches(path, lines)
  detect_nil_checks(path, lines)
  detect_validates_context(path, lines)
  detect_callback_blocks(path, lines)
end

# def から同じインデントの end までを1メソッドとみなす（整形済みコードを前提とする）
def each_method(lines)
  lines.each_with_index do |line, i|
    next unless line.match?(/^(\s*)def\s/)
    next if endless_def?(line)

    indent = line[/^\s*/]
    close = block_end_index(lines, i, indent)
    next if close.nil?

    yield(line[/def\s+([\w.?!=]+)/, 1], i, close)
  end
end

def detect_case_branches(path, lines)
  lines.each_with_index do |line, i|
    next unless line.match?(/^\s*(?:[\w@]+\s*=\s*)?case\b/)

    indent = line[/^\s*/]
    close = block_end_index(lines, i, indent)
    next if close.nil?

    whens = lines[(i + 1)...close].count { |l| l.match?(/^\s*when\b/) }
    emit(file: path, line: i + 1, signal: :case_when_branches, count: whens)
  end
end

def detect_nil_checks(path, lines)
  first_line = {}
  counts = Hash.new(0)
  methods = method_ranges(lines)

  lines.each_with_index do |line, i|
    line.scan(NIL_CHECK) do |receiver,|
      # 同名でも別メソッドのローカル変数なら別対象として数える。
      # 属性・関連・ivar（メソッド内で代入されない名前）だけがファイル全体で1つの対象になる。
      key = scoped_receiver(receiver, i, lines, methods)
      counts[key] += 1
      first_line[key] ||= i + 1
    end
  end

  counts.sort_by { |key, _| first_line[key] }.each do |key, count|
    emit(file: path, line: first_line[key], signal: :nil_checks_per_receiver, count: count)
  end
end

def method_ranges(lines)
  ranges = []
  each_method(lines) { |_name, start_index, end_index| ranges << (start_index..end_index) }
  ranges
end

def scoped_receiver(receiver, line_index, lines, methods)
  return receiver if receiver.include?(".")

  enclosing = methods.select { |range| range.cover?(line_index) }.min_by(&:size)
  return receiver if enclosing.nil?
  return receiver unless assigned_in?(receiver, lines[enclosing])

  "#{receiver}##{enclosing.begin + 1}"
end

# そのメソッド本体の中で代入されている名前か（= ローカル変数）
def assigned_in?(name, body)
  body.any? { |line| line.match?(/(?<![\w.:@])#{Regexp.escape(name)}\s*(?:,\s*\w+\s*)?=(?![=~>])/) }
end

def detect_validates_context(path, lines)
  lines.each_with_index do |line, i|
    emit(file: path, line: i + 1, signal: :validates_with_context, count: 1) if line.match?(VALIDATES_WITH_CONTEXT)
  end
end

def detect_callback_blocks(path, lines)
  lines.each_with_index do |line, i|
    next unless line.match?(/^\s*(?:after_commit|after_save)\b.*\bdo\b/)

    indent = line[/^\s*/]
    close = block_end_index(lines, i, indent)
    next if close.nil?

    emit(file: path, line: i + 1, signal: :callback_block_lines,
         count: code_line_count(lines[(i + 1)...close]))
  end
end

# --- TSX の検出 ---------------------------------------------------------

# 関数コンポーネントの宣言だけを拾う。`const SCHEMA = z.object({` や styled 定義には一致させない。
COMPONENT_HEAD = /
  ^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+[A-Z]\w*\s*[(<]
  |
  ^\s*(?:export\s+)?(?:default\s+)?const\s+[A-Z]\w*\s*(?::[^=]+)?=\s*
    (?:async\s*)?(?:function\b|\(|memo\(|forwardRef|React\.memo\()
/x
USE_STATE = /\buseState\s*[<(]/
# JSX の素通し（<Child value={value} />）。
# 「自分が props で受け取った名前を、そのまま同名で子へ渡している」コンポーネントだけを数える。
# JSX の親子チェーンは追跡しない。素通ししているコンポーネントの数で伝播の段数を近似する
# （兄弟へ同じ prop を配る場合は1コンポーネント＝1回。自前の useState を子へ渡すだけの場合は数えない）。
PROP_PASSTHROUGH = /(?<![\w.])([a-z]\w*)=\{\s*(\w+)\s*\}/

def strip_line_comments(lines)
  lines.map { |line| line.lstrip.start_with?("//") ? "\n" : line }
end

# 宣言部（引数の分割代入・型注釈のオブジェクト型・既定値のオブジェクト）を読み飛ばし、本体の `{` を探す。
# 戻り値は [本体開始行, 本体開始列]。式本体（`=> (` で JSX を返す形）は本体 `{` を持たないので nil。
def component_body_start(lines, start_index, fallback)
  head = COMPONENT_HEAD.match(lines[start_index])
  return [nil, nil] if head.nil?

  # 型注釈の `{}` を本体と誤認しないよう、代入や仮引数の開始位置より後ろだけを見る
  paren = head[0].end_with?("(") ? 1 : 0
  col = head.end(0)

  (start_index...fallback).each do |i|
    line = lines[i]

    (col...line.length).each do |c|
      case line[c]
      when "(" then paren += 1
      when ")" then paren -= 1
      when "{" then return [i, c] if paren <= 0
      end
    end
    # 引数リストを抜けた直後が `(` なら式本体。本体の `{` は存在しない
    return [nil, nil] if paren <= 0 && line[col..].to_s.match?(/=>\s*\(\s*$/)

    col = 0
  end

  [nil, nil]
end

# 宣言部のテキスト（コンポーネント名から本体の `{` の直前まで）
def signature_text(lines, start_index, body_start, body_col, fallback)
  if body_start
    lines[start_index...body_start].join + lines[body_start][0...body_col].to_s
  else
    # 式本体。`=>` を含む行までを宣言部とみなす
    arrow = (start_index...fallback).find { |i| lines[i].include?("=>") } || start_index
    lines[start_index..arrow].join
  end
end

# 宣言部のうち仮引数リスト以降だけを返す。`const A: React.FC<{ userId: string }> = (...)` のように
# 型注釈が先に来る形で、型のプロパティ名を受け取った props と誤認しないため。
def params_region(signature)
  head = COMPONENT_HEAD.match(signature)
  return signature if head.nil?

  rest = signature[head.end(0)..].to_s
  return rest if head[0].end_with?("(")

  open_index = rest.index("(")
  open_index ? rest[(open_index + 1)..].to_s : ""
end

# 仮引数リストから最初の波括弧グループ（＝分割代入）を取り出す。
def destructuring_group(signature)
  open_index = signature.index("{")
  return nil if open_index.nil?

  depth = 0
  (open_index...signature.length).each do |i|
    depth += 1 if signature[i] == "{"
    depth -= 1 if signature[i] == "}"
    return signature[(open_index + 1)...i] if depth.zero?
  end

  nil
end

# そのコンポーネントが props として受け取った名前。
# ({ userId, opts = {...} }) の分割代入と、(props) + 本体の const { userId } = props の両形式を拾う。
def received_props(signature, body)
  names = Set.new

  group = destructuring_group(params_region(signature))
  split_top_level(group.to_s).each do |element|
    name = element.strip[/\A[A-Za-z_]\w*/]
    names << name if name
  end

  body.join.scan(/const\s*\{([^}]*)\}\s*=\s*props\b/) do |inner,|
    split_top_level(inner).each do |element|
      name = element.strip[/\A[A-Za-z_]\w*/]
      names << name if name
    end
  end

  names
end

# 波括弧・丸括弧の内側を無視してカンマで分割する（既定値のオブジェクトで壊れないように）
def split_top_level(text)
  depth = 0
  text.each_char.slice_when { |char, _|
    depth += 1 if "{(".include?(char)
    depth -= 1 if "})".include?(char)
    depth.zero? && char == ","
  }.map { |chars| chars.join.delete_prefix(",") }
end

# 本体開始位置から波括弧の対応で終端を決める。対応が閉じなければ次の宣言／ファイル末尾で切る。
def component_end(lines, body_start, body_col, fallback)
  return fallback if body_start.nil?

  depth = 0

  (body_start...fallback).each do |i|
    text = i == body_start ? lines[i][body_col..] : lines[i]
    depth += text.count("{")
    depth -= text.count("}")
    return i + 1 if depth <= 0
  end

  fallback
end

def analyze_tsx(path, raw_lines, prop_hits)
  lines = strip_line_comments(raw_lines)
  heads = lines.each_index.select { |i| lines[i].match?(COMPONENT_HEAD) }

  heads.each_with_index do |start_index, n|
    fallback = heads[n + 1] || lines.size
    body_start, body_col = component_body_start(lines, start_index, fallback)
    signature = signature_text(lines, start_index, body_start, body_col, fallback)
    stop = component_end(lines, body_start, body_col, fallback)
    body = lines[start_index...stop]

    emit(file: path, line: start_index + 1, signal: :use_state_per_component,
         count: body.join.scan(USE_STATE).size)

    collect_prop_passthrough(path, body, start_index, signature, prop_hits)
  end
end

# 受け取った props の名前をそのまま子へ渡している場合だけ「素通し」として数える。
def collect_prop_passthrough(path, body, offset, signature, prop_hits)
  received = received_props(signature, body)
  seen = {}

  body.each_with_index do |line, i|
    line.scan(PROP_PASSTHROUGH) do |prop, value|
      next unless prop == value && received.include?(prop)

      seen[prop] ||= offset + i + 1
    end
  end

  seen.each do |prop, line|
    prop_hits[prop] ||= { count: 0, file: path, line: line }
    prop_hits[prop][:count] += 1
  end
end

# --- エントリポイント ---------------------------------------------------

def main(argv)
  if argv.empty? || argv.include?("-h") || argv.include?("--help")
    warn "usage: ruby detect.rb <path>... | --diff [<base>]"
    return argv.empty? ? 1 : 0
  end

  targets =
    if (i = argv.index("--diff"))
      diff_files(argv[i + 1])
    else
      argv
    end

  prop_hits = {}

  expand_targets(targets).each do |path|
    raw_lines = File.readlines(path)
    if RUBY_EXTS.include?(File.extname(path))
      analyze_ruby(path, raw_lines)
    elsif TSX_EXTS.include?(File.extname(path))
      analyze_tsx(path, raw_lines, prop_hits)
    end
  rescue StandardError => e
    warn "skip #{path}: #{e.class}: #{e.message}"
  end

  prop_hits.each do |_prop, hit|
    emit(file: hit[:file], line: hit[:line], signal: :prop_passthrough_components, count: hit[:count])
  end

  0
end

exit(main(ARGV)) if $PROGRAM_NAME == __FILE__
