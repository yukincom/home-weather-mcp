# Home Weather MCP

[English](README.md) · [MITライセンス](LICENSE)

自分で選んだ最大3地点の天気を、Hermesとの会話で確認できます。Open-Meteoを利用し、HermesをはじめMCP対応のクライアントで使えます。

**初期地点は東京**です。日本語・英語に対応しています。Open-Meteoの非商用サービスを利用する場合、APIキーは不要です。

## できること

- 現在・今日・明日の天気を確認する。
- 気温、湿度、風、降水確率、雨が降りそうな時間帯を聞く。
- 傘の案内や、一日の寒暖差が大きいときの声かけを受ける。
- 「自宅」「職場」などの呼び名や別名で地点を登録し、会話から変更する。
- 場所を指定しなかったときに使う地点を選ぶ。

## 導入

macOSまたはLinux、Python 3.11以上、[uv](https://docs.astral.sh/uv/)、インターネット接続が必要です。

```sh
git clone https://github.com/yukincom/hermes_whether_mcp.git
cd hermes_whether_mcp
uv sync --frozen
```

Hermesの`config.yaml`の既存の`mcp_servers`へ次の項目を追加してください。`/absolute/path/home-weather-mcp`は取得したフォルダの絶対パスに置き換え、既存の接続設定はそのまま残します。

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

追加後にMCPを再読み込み、またはHermesを再起動してください。その後の地点変更は再起動なしで反映されます。英語で使う場合は設定の`ja`を`en`に変えてください。

## 話しかけてみる

- 「今日の天気は？」— 場所を省略すると、初期設定では東京を使います。
- 「大阪市を『職場』として登録して。別名は『オフィス』」
- 「職場の明日の天気は？」
- 「職場の登録地点を京都市に変更して」
- 「場所を指定しなかったときは職場の天気にして」
- 「東京の呼び名を自宅に変えて、東京も別名として残して」
- 「今日の天気を英語で教えて」

登録できるのは最大3地点です。海外の場所は国名も一緒に伝えてください。候補が複数見つかった場合は、目的の場所を選べます。

## ライセンス・出典

ソフトウェアは[MITライセンス](LICENSE)です。天気は[Open-Meteo](https://open-meteo.com/)を利用し、[同サービスの利用条件・出典表示](https://open-meteo.com/en/pricing)に従います。地名検索には[Open-Meteo経由のGeoNames](https://open-meteo.com/en/docs/geocoding-api)と、必要に応じて[国土地理院](https://github.com/gsi-cyberjapan/gsimaps/issues/29)を使います。

エージェント・開発向けの資料：[Agent.md](Agent.md)。
