# ai_dotfiles

Claude Code のプラグイン（`plugins/`）と小さなツール（`tools/`）を1つにまとめたリポジトリ。
リポジトリを分けるほどでもないものを統合して管理する方針で、この形は維持する。

## プラグインを変更するときに毎回ハマる点

セッションをまたいで何度も調べ直したので、事実だけ残す。

- **中身を変えたら `plugin.json` の `version` も上げる。** キャッシュは
  `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` とバージョン単位で固定される。
  版を据え置くと `claude plugin marketplace update` を実行しても古い内容が使われ続け、
  `/plugin` の更新一覧にも現れない
- **更新の反映は `/plugin` から行う。** CLI の `claude plugin install` は既にインストール済みの
  プラグインに対して何もしない。実際に動いている版はスキル起動時の「Base directory」行で確認する
- **skill の frontmatter の `paths` は YAML リストで書く。** カンマ区切り文字列は公式ドキュメント上
  許容されているが、2.1.220 では**無言でスキルが読み込まれない**（エラーも警告も出ない）
- **`allowed-tools` の Bash ルールで展開されるのは `${CLAUDE_SKILL_DIR}` と `${CLAUDE_PROJECT_DIR}` だけ。**
  `${CLAUDE_PLUGIN_ROOT}` はリテラルのまま残りマッチしない
- **`claude plugin marketplace add <ローカルパス>` は同名の user スコープ登録を上書きする。**
  GitHub ソースに戻すには `claude plugin marketplace add <owner>/<repo>` で再登録する

## 作業の進め方

- 変更は `main` から新しいブランチを切る。プラグインごと・ツールごとに1コミット
- コミットメッセージ・コメント・ドキュメントは日本語
- PR はドラフトで作る。マージは人間が行う
