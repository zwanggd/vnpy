# VeighNa - トレーダーによる、トレーダーのための、AI駆動フレームワーク。

<p align="center">
  <img src ="https://vnpy.oss-cn-shanghai.aliyuncs.com/veighna-logo.png"/>
</p>

💬 **中国語**で読みたい方は [**こちら**](README.md) へ / **英語**で読みたい方は [**こちら**](README_ENG.md) へ

<p align="center">
    <img src ="https://img.shields.io/badge/version-4.3.0-blueviolet.svg"/>
    <img src ="https://img.shields.io/badge/platform-windows|linux|macos-yellow.svg"/>
    <img src ="https://img.shields.io/badge/python-3.10|3.11|3.12|3.13-blue.svg" />
    <img src ="https://img.shields.io/github/actions/workflow/status/vnpy/vnpy/pythonapp.yml?branch=master"/>
    <img src ="https://img.shields.io/github/license/vnpy/vnpy.svg?color=orange"/>
</p>

VeighNa は Python ベースのオープンソース・クオンツトレーディングシステム開発フレームワークであり、オープンソースコミュニティからの継続的な貢献により、機能豊富なクオンツトレーディングプラットフォームへと段階的に成長してきました。現在、ヘッジファンド、投資銀行、先物ブローカー、大学の研究機関、自己勘定取引会社など、国内外の金融機関の多くのユーザーに利用されています。

VeighNa を用いた二次開発（戦略、モジュールなど）についてご質問がある場合は、まず [**VeighNa プロジェクトドキュメント**](https://www.vnpy.com/docs/cn/index.html) をご確認ください。解決しない場合は、[**公式コミュニティフォーラム**](https://www.vnpy.com/forum/) の [質問とヘルプ] セクションでサポートを受けるか、[経験共有] セクションでご自身の経験を共有してください！

**VeighNa に関するより多くの情報を入手したいですか？** 下記の QR コードをスキャンしてアシスタントを追加し、[VeighNa コミュニティ交流 WeChat グループ] にご参加ください:

<p align="center">
  <img src ="https://vnpy.oss-cn-shanghai.aliyuncs.com/github_wx.png"/, width=250>
</p>


## AI 駆動

VeighNa リリース 10 周年を迎えたバージョン 4.0 では、AI クオンツ戦略を対象とした [vnpy.alpha](./vnpy/alpha) モジュールを正式に導入し、プロフェッショナルなクオンツトレーダー向けに **マルチファクター機械学習 (ML) 戦略の開発・研究・ライブトレーディングを一括で提供するオールインワンソリューション** を提供します:

<p align="center">
  <img src ="https://vnpy.oss-cn-shanghai.aliyuncs.com/alpha_demo.jpg"/, width=500>
</p>

* :bar_chart: **[dataset](./vnpy/alpha/dataset)**: ファクター特徴量エンジニアリング

    * ML アルゴリズムの学習最適化のために特別に設計されており、効率的なバッチ特徴量計算と処理をサポート
    * 豊富なファクター特徴量表現計算エンジンを内蔵し、学習データをワンクリックで迅速に生成可能
    * [Alpha 158](./vnpy/alpha/dataset/datasets/alpha_158.py): Microsoft の Qlib プロジェクト由来の株式市場特徴量コレクションで、ローソク足パターン、価格トレンド、時系列ボラティリティなど複数次元のクオンツファクターをカバー

* :bulb: **[model](./vnpy/alpha/model)**: 予測モデル学習

    * 標準化された ML モデル開発テンプレートを提供し、モデル構築と学習プロセスを大幅に簡素化
    * 統一された API インターフェース設計により、異なるアルゴリズム間のシームレスな切り替えとパフォーマンス比較テストをサポート
    * 主要な機械学習アルゴリズムを複数統合:
        * [Lasso](./vnpy/alpha/model/models/lasso_model.py): 古典的な Lasso 回帰モデル、L1 正則化による特徴量選択を実現
        * [LightGBM](./vnpy/alpha/model/models/lgb_model.py): 大規模データセットに最適化された学習エンジンを備えた効率的な勾配ブースティング決定木
        * [MLP](./vnpy/alpha/model/models/mlp_model.py): 多層パーセプトロンニューラルネットワーク、複雑な非線形関係のモデリングに適する

* :robot: **[strategy](./vnpy/alpha/strategy)**: 戦略の研究・開発

    * ML シグナル予測モデルに基づくクオンツトレーディング戦略を迅速に構築
    * クロスセクション・マルチアセット型、時系列・シングルアセット型の両方の戦略タイプをサポート

* :microscope: **[lab](./vnpy/alpha/lab.py)**: 研究プロセス管理

    * データ管理、モデル学習、シグナル生成、戦略バックテストを含む完全なワークフローを統合
    * シンプルな API 設計と組み込みの可視化分析ツールにより、戦略性能とモデル効果を直感的に評価可能

* :book: **[notebook](./examples/alpha_research)**: クオンツ研究デモ

    * [download_data_rq](./examples/alpha_research/download_data_rq.ipynb): RQData に基づく A 株指数構成銘柄データのダウンロード、指数構成銘柄の追跡と過去市場データの取得を含む
    * [download_data_xt](./examples/alpha_research/download_data_xt.ipynb): XtQuant データサービスに基づく A 株指数構成銘柄の変更履歴と株式ローソク足データのダウンロード
    * [research_workflow_lasso](./examples/alpha_research/research_workflow_lasso.ipynb): Lasso 回帰モデルに基づくクオンツ研究ワークフロー、線形モデルの特徴量選択と予測能力を実証
    * [research_workflow_lgb](./examples/alpha_research/research_workflow_lgb.ipynb): LightGBM 勾配ブースティングツリーに基づくクオンツ研究ワークフロー、効率的なアンサンブル学習手法を予測に活用
    * [research_workflow_mlp](./examples/alpha_research/research_workflow_mlp.ipynb): 多層パーセプトロンニューラルネットワークに基づくクオンツ研究ワークフロー、クオンツトレーディングにおけるディープラーニングの応用を実証

vnpy.alpha モジュールの設計思想は [Qlib](https://github.com/microsoft/qlib) プロジェクトに触発されたものであり、使いやすさを維持しつつ強力な AI クオンツ機能を提供しています。Qlib 開発チームに心より感謝申し上げます！


## 機能的特徴

:arrow_up: マークが付いているモジュールは、バージョン 4.0 の互換性アップグレードテストを完了しています。加えて、4.0 のコアフレームワークは互換性を優先するアップグレード方式を採用しているため、ほとんどのモジュールはそのまま利用可能です（C++ API のラップを伴うインターフェースは、使用前にアップグレードが必要）。

1. :arrow_up: 多機能クオンツトレーディングプラットフォーム (vnpy.trader)：様々なトレーディングインターフェースを統合し、特定の戦略アルゴリズムや機能開発のためのシンプルで使いやすい API を提供し、トレーダーが必要とするクオンツトレーディングアプリケーションを素早く構築可能

2. 国内外のあらゆる取引銘柄をカバーするトレーディングインターフェース (vnpy.gateway):

    * 国内市場

        * :arrow_up: CTP ([ctp](https://www.github.com/vnpy/vnpy_ctp)): 国内先物・オプション

        * :arrow_up: CTP Mini ([mini](https://www.github.com/vnpy/vnpy_mini)): 国内先物、オプション

        * :arrow_up: CTP Securities ([sopt](https://www.github.com/vnpy/vnpy_sopt)): ETF オプション

        * :arrow_up: FEMAS ([femas](https://www.github.com/vnpy/vnpy_femas)): 国内先物

        * :arrow_up: UFT ([uft](https://www.github.com/vnpy/vnpy_uft)): 国内先物、ETF オプション
        
        * :arrow_up: Esunny ([esunny](https://www.github.com/vnpy/vnpy_esunny)): 国内先物、上海金 (Gold TD)

        * :arrow_up: APEX HTS ([hts](https://www.github.com/vnpy/vnpy_hts)): ETF オプション

        * :arrow_up: XTP ([xtp](https://www.github.com/vnpy/vnpy_xtp)): 国内証券 (A 株)、ETF オプション

        * :arrow_up: TORA ([tora](https://www.github.com/vnpy/vnpy_tora)): 国内証券 (A 株)、ETF オプション
        
        * OST ([ost](https://www.github.com/vnpy/vnpy_ost)): 国内証券 (A 株)
        
        * EMT ([emt](https://www.github.com/vnpy/vnpy_emt)): 国内証券 (A 株)
        
        * SGIT ([sgit](https://www.github.com/vnpy/vnpy_sgit)): 上海金 (Gold TD)、国内先物

        * :arrow_up: KsGold ([ksgold](https://www.github.com/vnpy/vnpy_ksgold)): 上海金 (Gold TD)

        * :arrow_up: LStar ([lstar](https://www.github.com/vnpy/vnpy_lstar)): 先物アセットマネジメント

        * :arrow_up: Rohon ([rohon](https://www.github.com/vnpy/vnpy_rohon)): 先物アセットマネジメント

        * :arrow_up: Jees ([jees](https://www.github.com/vnpy/vnpy_jees)): 先物アセットマネジメント

        * ComStar ([comstar](https://www.github.com/vnpy/vnpy_comstar)): 銀行間市場
        
        * :arrow_up: TTS ([tts](https://www.github.com/vnpy/vnpy_tts)): 国内先物（シミュレーション）

    * 海外市場

        * :arrow_up: Interactive Brokers ([ib](https://www.github.com/vnpy/vnpy_ib)): グローバル証券、先物、オプション、為替など

        * :arrow_up: Esunny 9.0 ([tap](https://www.github.com/vnpy/vnpy_tap)): グローバル先物

        * :arrow_up: Direct Futures ([da](https://www.github.com/vnpy/vnpy_da)): グローバル先物

    * 特殊用途

        * :arrow_up: RQData マーケットデータ ([rqdata](https://www.github.com/vnpy/vnpy_rqdata)): クロスマーケット（株式、指数、ETF、先物）のリアルタイム市場データ

        * :arrow_up: XtQuant マーケットデータ ([xt](https://www.github.com/vnpy/vnpy_xt)): クロスマーケット（株式、指数、転換社債、ETF、先物、オプション）のリアルタイム市場データ

        * :arrow_up: RPC サービス ([rpc](https://www.github.com/vnpy/vnpy_rpcservice)): 分散アーキテクチャ向けのプロセス間通信インターフェース

3. 各種クオンツ戦略向けの、すぐに使えるトレーディングアプリケーション (vnpy.app):

    * :arrow_up: [cta_strategy](https://www.github.com/vnpy/vnpy_ctastrategy): CTA 戦略エンジンモジュール。使いやすさを維持しつつ、CTA 系戦略の運用中に注文管理を細かく制御可能（トレーディングスリッページの低減、高頻度戦略の実装）

    * :arrow_up: [cta_backtester](https://www.github.com/vnpy/vnpy_ctabacktester): CTA 戦略バックテスターモジュール。Jupyter Notebook を使わずに、GUI で直接戦略のバックテスト分析、パラメータ最適化などを実行可能

    * :arrow_up: [spread_trading](https://www.github.com/vnpy/vnpy_spreadtrading): スプレッド取引モジュール。カスタムスプレッド、スプレッド気配値・ポジションのリアルタイム計算をサポートし、半自動スプレッドアルゴリズム取引と全自動スプレッド戦略取引モードに対応

    * :arrow_up: [option_master](https://www.github.com/vnpy/vnpy_optionmaster): オプション取引モジュール。国内オプション市場向けに設計され、各種オプション価格モデル、インプライドボラティリティサーフェス計算、グリークス値リスクトラッキングなどの機能をサポート

    * :arrow_up: [portfolio_strategy](https://www.github.com/vnpy/vnpy_portfoliostrategy): ポートフォリオ戦略モジュール。複数銘柄同時取引のクオンツ戦略（Alpha、オプションアービトラージなど）向けに設計され、ヒストリカルデータのバックテストとライブ自動取引機能を提供

    * :arrow_up: [algo_trading](https://www.github.com/vnpy/vnpy_algotrading): アルゴリズム取引モジュール。TWAP、Sniper、Iceberg、BestLimit など、一般的な各種インテリジェント取引アルゴリズムを提供

    * :arrow_up: [script_trader](https://www.github.com/vnpy/vnpy_scripttrader): スクリプト戦略モジュール。マルチアセットポートフォリオ取引戦略と計算タスク向けに設計され、コマンドラインから直接 REPL 指示取引も実行可能。バックテスト機能は非対応

    * :arrow_up: [paper_account](https://www.github.com/vnpy/vnpy_paperaccount): シミュレーション取引モジュール。完全にローカル実装されたシミュレーション取引機能で、トレーディングインターフェースから取得したリアルタイム気配値に基づき注文マッチングを行い、注文約定プッシュとポジション記録を提供

    * :arrow_up: [chart_wizard](https://www.github.com/vnpy/vnpy_chartwizard): ローソク足チャートモジュール。RQData データサービス（先物）またはトレーディングインターフェースから取得したヒストリカルデータに、Tick プッシュを組み合わせてリアルタイムの市場変動を表示

    * :arrow_up: [portfolio_manager](https://www.github.com/vnpy/vnpy_portfoliomanager): ポートフォリオモジュール。各種ファンダメンタル取引戦略向けに、戦略別サブアカウントに基づき、取引ポジションの自動追跡とリアルタイムの損益統計を提供

    * :arrow_up: [rpc_service](https://www.github.com/vnpy/vnpy_rpcservice): RPC サービスモジュール。VeighNa Trader プロセスをサーバーとして起動し、気配値と取引の統一ルーティングチャネルとして機能させ、複数クライアントの同時接続によりマルチプロセス分散システムを実現

    * :arrow_up: [data_manager](https://www.github.com/vnpy/vnpy_datamanager): ヒストリカルデータ管理モジュール。ツリーディレクトリでデータベース内の既存データを表示し、任意の期間のデータを選択してフィールド詳細を表示可能。CSV ファイルのデータインポート・エクスポートをサポート

    * :arrow_up: [data_recorder](https://www.github.com/vnpy/vnpy_datarecorder): 市場データ記録モジュール。GUI で設定し、需要に応じて Tick またはローソク足データをリアルタイムにデータベースに記録。戦略バックテストやライブ初期化に利用可能

    * :arrow_up: [excel_rtd](https://www.github.com/vnpy/vnpy_excelrtd): Excel RTD (Real Time Data) リアルタイムデータサービス。pyxll モジュールに基づき、各種データ（気配値、銘柄、ポジションなど）を Excel にリアルタイムプッシュ更新

    * :arrow_up: [risk_manager](https://www.github.com/vnpy/vnpy_riskmanager): リスク管理モジュール。取引フロー制御、発注数、有効注文数、総取消注文数などのルールに関する統計と制限を提供し、フロントエンドのリスク管理機能を効果的に実装
    
    * :arrow_up: [web_trader](https://www.github.com/vnpy/vnpy_webtrader): Web サービスモジュール。B-S アーキテクチャの要件に従って設計され、能動的関数呼び出し (REST) と受動的データプッシュ (WebSocket) を提供する Web サーバーを実装


4. Python トレーディング API インターフェースパッケージ (vnpy.api)。上記トレーディングインターフェースの基盤実装を提供:
    
    * :arrow_up: REST Client ([rest](https://www.github.com/vnpy/vnpy_rest)): コルーチンによる非同期 IO に基づく高性能 REST API クライアント。イベントメッセージループのプログラミングモデルを採用し、高並列リアルタイム取引リクエストの送信をサポート
    
    * :arrow_up: Websocket Client ([websocket](https://www.github.com/vnpy/vnpy_websocket)): コルーチンによる非同期 IO に基づく高性能 Websocket API クライアント。REST Client とのイベントループ共有をサポートし、GIL によるマルチスレッド性能劣化を回避


5. :arrow_up: シンプルで使いやすいイベント駆動エンジン (vnpy.event)。イベント駆動型トレーディングプログラムの中核

6. 各種データベースと接続する標準化された管理クライアント (vnpy.database):

    * SQL 系

        * :arrow_up: SQLite ([sqlite](https://www.github.com/vnpy/vnpy_sqlite)): 軽量な単一ファイルデータベース。データサービスプログラムのインストール・設定不要で、VeighNa のデフォルトオプション。初心者ユーザーに適する

        * :arrow_up: MySQL ([mysql](https://www.github.com/vnpy/vnpy_mysql)): 世界で最も人気のあるオープンソースのリレーショナルデータベース。ドキュメントが極めて豊富で、他の NewSQL 互換実装（TiDB など）に置き換え可能

        * :arrow_up: PostgreSQL ([postgresql](https://www.github.com/vnpy/vnpy_postgresql)): より機能豊富なオープンソースのリレーショナルデータベース。拡張プラグインによる新機能サポート。上級ユーザー向け

    * NoSQL 系
    
        * DolphinDB ([dolphindb](https://www.github.com/vnpy/vnpy_dolphindb)): 高速性が要求される低レイテンシまたはリアルタイムタスクに特に適した、高性能な分散時系列データベース
        
        * :arrow_up: TDengine ([taos](https://www.github.com/vnpy/vnpy_taos)): 分散、高性能、SQL 対応の時系列データベース。キャッシュ、ストリーム計算、データ購読などのシステム機能を内蔵し、開発・保守の複雑さを大幅に軽減
        
        * :arrow_up: MongoDB ([mongodb](https://www.github.com/vnpy/vnpy_mongodb)): 分散ファイルストレージ (bson 形式) に基づく非リレーショナルデータベース。ホットデータのメモリキャッシュを内蔵し、読み書き速度が高速

7. 各種データサービス向けアダプターインターフェース (datafeed):

    * :arrow_up: XtQuant ([xt](https://www.github.com/vnpy/vnpy_xt)): 株式、先物、オプション、ファンド、債券

    * :arrow_up: RQData ([rqdata](https://www.github.com/vnpy/vnpy_rqdata)): 株式、先物、オプション、ファンド、債券、上海金 (Gold TD)

    * :arrow_up: MultiCharts ([mcdata](https://www.github.com/vnpy/vnpy_mcdata)): 先物、先物オプション
    
    * :arrow_up: TuShare ([tushare](https://www.github.com/vnpy/vnpy_tushare)): 株式、先物、オプション、ファンド
    
    * :arrow_up: Wind ([wind](https://www.github.com/vnpy/vnpy_wind)): 株式、先物、ファンド、債券
    
    * :arrow_up: iFinD ([ifind](https://www.github.com/vnpy/vnpy_ifind)): 株式、先物、ファンド、債券
    
    * :arrow_up: TQSDK ([tqsdk](https://www.github.com/vnpy/vnpy_tqsdk)): 先物

    * :arrow_up: GoldMiner ([gm](https://www.github.com/vnpy/vnpy_gm)): 株式
    
    * :arrow_up: polygon ([polygon](https://www.github.com/vnpy/vnpy_polygon)): 株式、先物、オプション

8. :arrow_up: 分散デプロイで複雑なトレーディングシステムを実装するためのプロセス間通信の標準コンポーネント (vnpy.rpc)

9. :arrow_up: Python 製の高性能ローソク足チャート (vnpy.chart)。大量データのチャート表示とリアルタイムデータ更新機能をサポート

10. [コミュニティフォーラム](http://www.vnpy.com/forum) と [Zhihu ブログ](http://zhuanlan.zhihu.com/vn-py)。VeighNa プロジェクトの開発チュートリアルや、クオンツトレーディング分野における Python の応用に関する研究などを掲載

11. 公式交流グループ 262656087 (QQ)。厳格な管理（長期非アクティブメンバーの定期整理）を実施しており、会費は VeighNa コミュニティファンドに寄付されます。

注: 上記の機能的特徴の説明は公開時点のドキュメントに基づくものであり、その後の更新や調整が存在する可能性があります。機能説明と実際の状況に相違がある場合は、Issue でご連絡の上、調整をお願いします。

## 環境準備

* Python ディストリビューション [VeighNa Studio-4.3.0](https://download.vnpy.com/veighna_studio-4.3.0.exe) のご利用を推奨します。最新版の VeighNa フレームワークと VeighNa Station クオンツ管理プラットフォームを含む、VeighNa チームがクオンツトレーディング向けに特別に構築したもので、手動インストール不要です。
* 対応 OS: Windows 11 以上 / Windows Server 2022 以上 / Ubuntu 22.04 LTS 以上
* 対応 Python バージョン: Python 3.10 以上 (64-bit)、**Python 3.13 推奨**

## インストール手順

最新バージョンを [こちら](https://github.com/vnpy/vnpy/releases) からダウンロードし、解凍後、以下のコマンドを実行してインストールしてください。

**Windows**

```
install.bat
```

**Ubuntu**

```
bash install.sh
```

**Macos**

```
bash install_osx.sh
```

## ユーザーガイド

1. [SimNow](http://www.simnow.com.cn/) で CTP デモアカウントを登録し、[このページ](http://www.simnow.com.cn/product.action) でブローカーコードおよび取引・気配値サーバーアドレスを取得します。

2. [VeighNa コミュニティフォーラム](https://www.vnpy.com/forum/) で登録し、VeighNa Station のアカウントとパスワードを取得します（フォーラムのアカウント・パスワードを使用）

3. VeighNa Station を起動（VeighNa Studio インストール後、デスクトップにショートカットが自動作成されます）し、前のステップで取得したアカウント・パスワードを入力してログインします

4. 画面下部の **VeighNa Trader** ボタンをクリックし、取引を開始しましょう！

注意:

* VeighNa Trader 実行中に VeighNa Station を閉じないでください（自動的に終了します）

## スクリプト実行

VeighNa Station によるグラフィカルな起動方式の他に、任意のディレクトリで run.py を作成し、以下のサンプルコードを記述する方法もあります:

```Python
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import MainWindow, create_qapp

from vnpy_ctp import CtpGateway
from vnpy_ctastrategy import CtaStrategyApp
from vnpy_ctabacktester import CtaBacktesterApp


def main():
    """Start VeighNa Trader"""
    qapp = create_qapp()

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    
    main_engine.add_gateway(CtpGateway)
    main_engine.add_app(CtaStrategyApp)
    main_engine.add_app(CtaBacktesterApp)

    main_window = MainWindow(main_engine, event_engine)
    main_window.showMaximized()

    qapp.exec()


if __name__ == "__main__":
    main()
```

そのディレクトリで CMD を開き（Shift 押下 → 右クリック → ここでコマンドウィンドウ / PowerShell を開く）、以下のコマンドを実行して VeighNa Trader を起動します:

    python run.py
    
## コード貢献

VeighNa はソースコードのホスティングに GitHub を利用しています。コードを貢献したい場合は、GitHub の PR (Pull Request) プロセスをご利用ください:

1. [Issue の作成](https://github.com/vnpy/vnpy/issues/new) - 大きな変更（新機能、大規模リファクタリングなど）の場合は、まず Issue で議論することが望ましく、小さな改善（ドキュメント改善、バグ修正など）は直接 PR を送ることが可能です

2. [VeighNa](https://github.com/vnpy/vnpy) を Fork - 右上の **Fork** ボタンをクリック

3. 自分の fork を clone: ```git clone https://github.com/$userid/vnpy.git```

	* fork が古くなった場合は、手動で同期する必要があります: [同期方法](https://help.github.com/articles/syncing-a-fork/)

4. **dev** から自分のフィーチャーブランチを作成: ```git checkout -b $my_feature_branch dev```

5. $my_feature_branch で変更を加え、自分の fork に push

6. fork の $my_feature_branch ブランチからメインプロジェクトの **dev** ブランチに対して [Pull Request] を作成 - [こちら](https://github.com/vnpy/vnpy/compare?expand=1) で **compare across forks** をクリックし、必要な fork とブランチを選択して PR を作成

7. レビューを待ち、改善を続けるか、Merge されます！

コードを提出する際には、コード品質向上のため以下のルールを遵守してください:

  * [ruff](https://github.com/astral-sh/ruff) を使用してコードスタイルをチェックし、エラーや警告がないことを確認してください。プロジェクトルートディレクトリで ``ruff check .`` を実行するだけです。
  * [mypy](https://github.com/python/mypy) を使用して静的型チェックを行い、型アノテーションが正しいことを確認してください。プロジェクトルートディレクトリで ``mypy vnpy`` を実行するだけです。


## その他のコンテンツ

* [ヘルプの入手](https://github.com/vnpy/vnpy/blob/dev/.github/SUPPORT.md)
* [コミュニティ行動指針](https://github.com/vnpy/vnpy/blob/dev/.github/CODE_OF_CONDUCT.md)
* [Issue テンプレート](https://github.com/vnpy/vnpy/blob/dev/.github/ISSUE_TEMPLATE.md)
* [PR テンプレート](https://github.com/vnpy/vnpy/blob/dev/.github/PULL_REQUEST_TEMPLATE.md)


## 著作権表示

MIT
