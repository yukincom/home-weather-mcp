# Home Weather MCP

[English](README.md) · [MITライセンス](LICENSE)

Open-Meteoを使い、最大3地点の天気を必要なときだけ取得する独立したstdio MCPサーバーです。Hermes本体やその内部APIには依存しません。

初期地点は**東京**、呼び出し名は`Tokyo`と`東京`です。場所を省略するとデフォルト地点を使用します。英語・日本語に対応し、地点・呼び出し名・別名・デフォルトは会話から変更できます。

## 導入

macOS/Linux、Python 3.11以上、uvが必要です。

```sh
uv sync --frozen
.venv/bin/python -m home_weather.server --language ja
```

これはMCPクライアントから呼び出すプロセスです。直接実行すると標準入出力で接続を待ちます。

Hermesの`config.yaml`の既存の`mcp_servers`へ追加してください。パスは実際の絶対パスに置き換えます。

```yaml
mcp_servers:
  home_weather:
    command: /absolute/path/home-weather-mcp/.venv/bin/python
    args: ["-m", "home_weather.server", "--language", "ja"]
    enabled: true
    timeout: 60
    connect_timeout: 20
    supports_parallel_tool_calls: false
    tools:
      resources: false
      prompts: false
```

追加後にMCPを再読み込み、またはHermesを再起動してください。地点変更時には再起動不要です。

地点設定の保存先は`~/.config/home-weather-mcp/locations.json`です。`--config`または`HOME_WEATHER_CONFIG`で変更できます。設定ファイルがない場合は東京を使い、最初の設定変更でファイルを作ります。明示的に空にした設定へ東京を再追加することはありません。

## 指示例

- 「今日の天気は？」
- 「大阪市を『職場』として登録して。別名は『オフィス』」
- 「職場の明日の天気は？」
- 「職場の登録地点を京都市に変更して」
- 「場所を指定しなかったときは職場の天気にして」
- 「東京の呼び名を自宅に変えて、東京も別名として残して」
- 「今日の天気を英語で教えて」

地名検索で候補が複数ある場合は候補選択後に保存します。海外は`country_code`を指定してください（既定`JP`）。地名変更では座標を再検索します。別名一覧の変更は置換で、省略した項目は維持します。

## 機能

- 現在／今日／明日の天気。気温、体感温度、湿度、風、降水確率、雨の時間帯と傘・気温・寒暖差の案内。
- 今日の雨の時間帯はこのあと、明日は一日全体。日別の最高・最低気温と最大降水確率は一日全体です。
- 定時取得、天気キャッシュ、天気ファイル保存、Obsidian書き込みはありません。保存するのは地点設定だけです。会話履歴の保存はクライアント側の設定に従います。
- `weather_get`の`language=en|ja`で切替。日別予報には`summary_en`・`summary_ja`と選択言語の`summary`を返します。ツール説明・エラーは英語です。
- 接続失敗・タイムアウトは1回再試行。時間別の取得だけが失敗した場合は警告付きの日別予報を返します。

ツール一覧・引数の詳細は[英語README](README.md#tools)を参照してください。

## テスト・CI

```sh
uv sync --frozen
uv run --frozen pytest -q
uv build
```

GitHub Actionsはpushとpull requestでLinux/macOS、Python 3.11/3.14のテストとビルドを実行します。天気APIはテスト内で模擬し、外部APIへの接続やキーは不要です。GitHub上の結果はアップロード後に確認できます。

ソフトウェアは[MITライセンス](LICENSE)。天気データは[Open-Meteo](https://open-meteo.com/)、地名はGeoNamesと必要に応じて国土地理院を使用し、それぞれの利用条件に従います。
