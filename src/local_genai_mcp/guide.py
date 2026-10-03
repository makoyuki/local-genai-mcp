from .config import Config


def build_guide(config: Config) -> str:
    """使い方・頼み方のガイド。config.toml の既定値を埋め込んで返す。"""
    parts = ["# local-genai の使い方", ""]

    if config.ollama.enabled:
        o = config.ollama
        parts += [
            "## ローカルLLM(Ollama)",
            "",
            f"- 既定のモデル: {o.default_model or '(未設定。毎回指定が必要)'}",
            f"- 思考(think): 既定は{'オン' if o.think else 'オフ'}"
            "(qwen3.5 や deepseek-r1 など、答える前に考えるモデルで有効。オンにすると遅いが込み入った問いに強い)",
            "",
            "頼み方の例:",
            "- 「ローカルのモデルの一覧を見せて」 → 入っているモデルと、読み込み中のものを表示",
            "- 「この文章をOllamaで要約して」 → 既定のモデルで処理",
            "- 「llama3.1:8b でこの文章を英訳して」 → モデルを指定(名前はモデルの一覧で確認)",
            "- 「qwen3.5で、じっくり考えて答えさせて」 → 思考をオンにして実行",
            "",
        ]

    if config.forge.enabled:
        d = config.forge.defaults
        size = f"{d.width}x{d.height}"
        if d.enable_hr:
            final = f"{round(d.width * d.hr_scale)}x{round(d.height * d.hr_scale)}"
            hires = f"オン(x{d.hr_scale:g}、{d.hr_upscaler}、描き直しの強さ {d.denoising_strength:g})→ 仕上がり {final}"
        else:
            hires = "オフ"
        parts += [
            "## 画像生成(Forge Neo)",
            "",
            f"- 既定の大きさ: {size}(Hires.fix 前の大きさ)",
            f"- Hires.fix(拡大して描き直し、細部をくっきりさせる): {hires}",
            f"- 既定: steps {d.steps}、CFG {d.cfg_scale:g}、サンプラー {d.sampler_name}",
            f"- 保存先: {config.forge.output_dir}",
            "- プロンプトは WebUI1111 と同じ書き方((word:1.2) の強調、<lora:名前:重み>)が使える",
            "",
            "頼み方の例:",
            "- 「夕焼けの海辺を歩く猫を1枚描いて」 → 既定の設定で生成",
            "- 「縦長で」「832x1216で」 → 大きさを指定(Hires.fix 後はその倍率分大きくなる)",
            "- 「Hires.fixなしで」「1.5倍で」「描き直しを弱めに(0.3)」 → Hires.fix を調整",
            "- 「シード 12345 で」「4枚まとめて」 → シード値・枚数を指定",
            "- 「使えるモデルの一覧を見せて」「LoRAの一覧を見せて」「サンプラーの一覧を見せて」",
            "- 「(モデル名)で描いて」 → モデルを切り替えて生成(名前はモデルの一覧で確認)"
            "。Forge Neo 側で選ばれているモデルも切り替わったままになる。切り替えには数十秒かかる",
            "- 「output フォルダに保存して」 → 保存先を指定",
            "",
        ]

    parts += [
        "## うまくいかないとき",
        "",
        "- 「local-genai の接続を確認して」 → 各サービスにつながるかを確認",
        f"- 既定値は {config.source or 'config.toml'} で変えられる(変えたら Claude Code を起動し直す)",
    ]
    return "\n".join(parts)
