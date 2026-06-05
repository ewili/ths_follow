"""
此模块用于增强 easytrader.grid_strategies.Copy 类的验证码处理能力。
使用 ddddocr 进行验证码识别（纯 Python 实现，无需系统依赖）。

使用方法：
    import app.utils.easytrader_copy_patch  # 在 _ensure_easytrader() 中导入即可

修复要点：Copy.get() 在调用 _get_clipboard_data() 之前会执行 _set_foreground(grid)，
这会将验证码对话框压到主窗口后面，导致 top_window() 返回主窗口而非验证码。
因此使用 _find_captcha_dialog() 遍历所有顶层窗口来查找验证码对话框。
"""
import io
import logging
import time as _time_module

import pywinauto.clipboard
from easytrader.log import logger as et_logger
from easytrader.grid_strategies import Copy
from PIL import Image

_CAPTCHA_IMG_PATH = "tmp.png"


def _type_captcha_via_wm_char(editor, text):
    """通过 WM_CHAR 消息逐字符输入验证码，不依赖窗口焦点/前台状态。

    set_edit_text (WM_SETTEXT) 不会触发 EN_CHANGE 通知，
    导致同花顺客户端不识别输入内容；
    type_keys 依赖 SetForegroundWindow，在模态弹窗下失败。
    WM_CHAR 模拟真实键盘输入，触发完整通知链，且不依赖焦点。

    清空策略：先 EM_SETSEL 全选，再逐字符 WM_CHAR 输入覆盖。
    Edit 控件在存在选中文本时，WM_CHAR 会自动替换选中内容，
    因此第一个 WM_CHAR 字符会替换全部旧文本，无需显式删除。
    注意：WM_SETTEXT("") 会破坏 THS Edit 控件的内部状态，
    导致后续 WM_CHAR 被吞掉，不可使用。
    """
    try:
        hwnd = editor.element_info.handle
    except Exception:
        hwnd = None
    if hwnd is None:
        # 无法获取句柄时回退到 set_edit_text
        editor.set_edit_text(text)
        return
    import win32con
    import win32gui
    # 全选输入框内容（后续 WM_CHAR 会自动替换选中内容）
    win32gui.SendMessage(hwnd, win32con.EM_SETSEL, 0, -1)
    # 逐字符发送 WM_CHAR（第一个字符会替换所有选中内容）
    for ch in text:
        win32gui.SendMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)

# ddddocr 单例（延迟初始化）
_ddddocr_instance = None      # beta 模型
_ddddocr_old_instance = None  # 默认模型

# 统一日志：双写 easytrader 与 app.captcha，便于主日志查看
logger = logging.getLogger("app.captcha")
logger.setLevel(logging.INFO)


def _log(level: int, msg: str, *args, **kwargs) -> None:
    et_logger.log(level, msg, *args, **kwargs)
    logger.log(level, msg, *args, **kwargs)


def _get_ddddocr():
    """获取 ddddocr beta 模型单例，并设置字符范围。"""
    global _ddddocr_instance
    if _ddddocr_instance is None:
        import ddddocr
        _ddddocr_instance = ddddocr.DdddOcr(show_ad=False, beta=True)
        _ddddocr_instance.set_ranges("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return _ddddocr_instance


def _get_ddddocr_old():
    """获取 ddddocr 默认模型单例，并设置字符范围。"""
    global _ddddocr_old_instance
    if _ddddocr_old_instance is None:
        import ddddocr
        _ddddocr_old_instance = ddddocr.DdddOcr(show_ad=False)
        _ddddocr_old_instance.set_ranges("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return _ddddocr_old_instance


def _captcha_recognize_ddddocr(img_path: str) -> str:
    """使用 ddddocr 识别验证码图片（单次，无预处理）。
    
    Args:
        img_path: 验证码图片路径
        
    Returns:
        识别出的验证码字符串
    """
    from PIL import Image
    
    ocr = _get_ddddocr()
    img = Image.open(img_path)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    result = ocr.classification(img_bytes.getvalue())
    return result


def _height_case_correct(img_bytes: bytes, text: str) -> str:
    """基于原图列投影切片与相对高度比例修正大小写。
    
    相比绝对高度，相对高度能完美适应验证码图片的边缘留白（Padding）。
    步骤：
    1. 灰度原图进行 Otsu 二值化；
    2. 投影计算所有含文本的列边界，切分为 4 个垂直段；
    3. 每段计算带有噪声阈值（row_sum >= min_pixels）的字符高度，排除孤立噪点；
    4. 取 4 个段的最大高度 max_h 作为当前验证码的最矮基准（最少也是一个大写/数字高度）；
    5. 计算每个字符段的相对高度比 rel_h = h / max_h：
       - rel_h > 0.82 倾向于大写
       - rel_h < 0.72 倾向于小写
       - 针对大小写易混淆字母（c, k, m, o, p, s, u, v, w, x, z）进行更积极的修正。
    """
    if len(text) != 4:
        return text
    try:
        import cv2
        import numpy as np
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return text
        img_h, img_w = img.shape[:2]
        if img_h == 0 or img_w == 0:
            return text
        
        # 二值化（黑字白底变白字黑底，方便sum计算）
        _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # 将255归一化为1，方便计数
        bw_bin = (bw > 0).astype(np.uint8)
        
        # 计算列投影以确定字符的水平边界，忽略前2%和后2%的边界噪声
        col_sum = bw_bin.sum(axis=0)
        border_w = max(1, int(img_w * 0.02))
        cols = np.where(col_sum > 0)[0]
        cols = [c for c in cols if border_w <= c < img_w - border_w]
        if len(cols) < 10:
            return text
            
        min_col, max_col = cols[0], cols[-1]
        span = max_col - min_col + 1
        char_w = span / 4.0
        
        # 计算每段的真实高度（带有噪声过滤）
        heights = []
        for i in range(4):
            c_start = int(min_col + i * char_w)
            c_end = int(min_col + (i + 1) * char_w)
            sub = bw_bin[:, c_start:c_end]
            
            # 计算每行的像素数
            row_sum = sub.sum(axis=1)
            # 过滤：每行必须至少有 2 个像素（或 8% 的字符宽度），否则视为噪点
            min_pixels = max(2, int(char_w * 0.08))
            rows = np.where(row_sum >= min_pixels)[0]
            if len(rows) > 0:
                h = rows[-1] - rows[0] + 1
                heights.append(h)
            else:
                heights.append(0)
                
        max_h = max(heights)
        if max_h == 0:
            return text
            
        result = []
        for i, ch in enumerate(text):
            if not ch.isalpha():
                result.append(ch)
                continue
            h = heights[i]
            
            # 大小写易混淆字符
            is_ambiguous = ch.lower() in ['c', 'k', 'm', 'o', 'p', 's', 'u', 'v', 'w', 'x', 'z']
            
            if max_h <= 36:
                # 整个验证码中没有任何大写字母或高位字符，全部都是矮字符 (28-33px)
                # 此时应该将所有易混淆字符强制转为小写
                if is_ambiguous:
                    result.append(ch.lower())
                else:
                    if h <= 34:
                        result.append(ch.lower())
                    else:
                        result.append(ch)
            else:
                # 存在高位字符或大写字母，采用高精度的相对比例判断
                rel_h = h / max_h
                if is_ambiguous:
                    if rel_h > 0.80:
                        result.append(ch.upper())
                    elif rel_h < 0.72:
                        result.append(ch.lower())
                    else:
                        result.append(ch)
                else:
                    if rel_h > 0.85:
                        result.append(ch.upper())
                    elif rel_h < 0.70:
                        result.append(ch.lower())
                    else:
                        result.append(ch)
                    
        corrected = "".join(result)
        if corrected != text:
            _log(logging.INFO, "captcha height case correct: %s -> %s (max_h=%d, heights=%s, rel_hatios=%s)", 
                 text, corrected, max_h, heights, [f"{h/max_h:.2f}" if max_h > 0 else "0.00" for h in heights])
        return corrected
    except Exception as e:
        _log(logging.ERROR, "captcha height case correct failed: %s", e)
        return text


def _ocr_classify(img_bytes: bytes, png_fix: bool = True) -> str:
    """用 ddddocr beta 模型识别图片字节，返回清洗后的字母数字字符串。"""
    ocr = _get_ddddocr()
    raw = ocr.classification(img_bytes, png_fix=png_fix)
    return "".join(c for c in raw.strip() if c.isalnum())


def _ocr_classify_old(img_bytes: bytes, png_fix: bool = True) -> str:
    """用 ddddocr 默认模型识别图片字节，返回清洗后的字母数字字符串。"""
    ocr = _get_ddddocr_old()
    raw = ocr.classification(img_bytes, png_fix=png_fix)
    return "".join(c for c in raw.strip() if c.isalnum())


def _pil_to_png_bytes(pil_img) -> bytes:
    """PIL Image → PNG 字节。"""
    buf = io.BytesIO()
    pil_img.save(buf, format='PNG')
    return buf.getvalue()


# ── 5 种 OpenCV 预处理方法 ──────────────────────────────────────

def _preprocess_adaptive_threshold(img_path: str) -> bytes:
    """方法 A：灰度 → 自适应阈值二值化。"""
    import cv2
    import numpy as np
    img = cv2.imread(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 11, 2)
    pil_img = Image.fromarray(binary)
    return _pil_to_png_bytes(pil_img)


def _preprocess_upscale_sharpen(img_path: str) -> bytes:
    """方法 B：灰度 → 2x 超分放大（双三次插值）→ 锐化核 → 二值化。"""
    import cv2
    import numpy as np
    img = cv2.imread(img_path)
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    img = cv2.filter2D(img, -1, kernel)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    pil_img = Image.fromarray(binary)
    return _pil_to_png_bytes(pil_img)


def _preprocess_contrast_denoise(img_path: str) -> bytes:
    """方法 C：灰度 → 对比度增强 3x → 高斯模糊去噪 → 二值化。"""
    import cv2
    import numpy as np
    img = cv2.imread(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.convertScaleAbs(gray, alpha=3.0, beta=0)
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    pil_img = Image.fromarray(binary)
    return _pil_to_png_bytes(pil_img)


def _preprocess_multi_threshold(img_path: str) -> bytes:
    """方法 D：灰度 → 多阈值尝试，取 ddddocr 最多票结果。
    
    对 5 个不同阈值分别二值化后识别，返回得票最多的结果对应的图片字节。
    """
    import cv2
    import numpy as np
    from collections import Counter
    img = cv2.imread(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresholds = [100, 128, 150, 180, 200]
    results = []
    for th in thresholds:
        _, binary = cv2.threshold(gray, th, 255, cv2.THRESH_BINARY)
        pil_img = Image.fromarray(binary)
        img_bytes = _pil_to_png_bytes(pil_img)
        res = _ocr_classify(img_bytes)
        if len(res) == 4:
            results.append((res, img_bytes))
    if not results:
        # 回退：用 Otsu 阈值
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        pil_img = Image.fromarray(binary)
        return _pil_to_png_bytes(pil_img)
    # 投票选最多
    counter = Counter(r for r, _ in results)
    best = counter.most_common(1)[0][0]
    for r, b in results:
        if r == best:
            return b
    return results[0][1]


def _preprocess_raw(img_path: str) -> bytes:
    """方法 E：原图直传（baseline）。"""
    from PIL import Image
    img = Image.open(img_path)
    return _pil_to_png_bytes(img)


# ── 多方法投票识别 ──────────────────────────────────────────────

def _captcha_recognize_multi(img_path: str) -> str:
    """多预处理 + 双模型 ddddocr 投票识别验证码。
    
    5 种预处理方法 × 2 个模型（beta + 默认）分别识别，
    仅保留长度=4 的有效结果。
    投票策略：先统一大写投票确定字符内容，
    再用 probability 输出确定每个字符的大小写。
    识别前将原图放大 3x，提升 OCR 识别和高度判断精度。
    识别完成后保存图片副本和识别记录到 captcha_debug/ 目录。
    """
    import os
    import shutil
    import datetime
    from collections import Counter
    # 放大原图 3x，提升 OCR 识别和高度判断精度
    try:
        _img = Image.open(img_path)
        _img = _img.resize((_img.width * 3, _img.height * 3), Image.LANCZOS)
        _img.save(img_path)
    except Exception:
        pass
    preprocessors = [
        ("adaptive", _preprocess_adaptive_threshold),
        ("upscale", _preprocess_upscale_sharpen),
        ("contrast", _preprocess_contrast_denoise),
        ("multi_th", _preprocess_multi_threshold),
        ("raw", _preprocess_raw),
    ]
    results = []
    for name, fn in preprocessors:
        try:
            img_bytes = fn(img_path)
            # beta 模型识别
            res_beta = _ocr_classify(img_bytes)
            if len(res_beta) == 4:
                results.append(res_beta)
                _log(logging.DEBUG, "captcha method %s(beta): %s", name, res_beta)
            # 默认模型识别
            res_old = _ocr_classify_old(img_bytes)
            if len(res_old) == 4:
                results.append(res_old)
                _log(logging.DEBUG, "captcha method %s(old): %s", name, res_old)
        except Exception as e:
            _log(logging.WARNING, "captcha method %s failed: %s", name, e)
    if not results:
        _log(logging.ERROR, "captcha all methods produced no valid result")
        return "", []
    # 投票策略：按大写分组确定字符内容
    upper_groups = {}
    for r in results:
        key = r.upper()
        upper_groups.setdefault(key, []).append(r)
    # 选总票数最多的大写组
    best_upper = max(upper_groups, key=lambda k: len(upper_groups[k]))
    group_results = upper_groups[best_upper]
    # 基于原图的高度判断：对原图做 _height_case_correct 获取大小写判断
    # 将高度判断结果作为额外 2 票加入投票，打破 OCR 大写分歧
    try:
        with open(img_path, "rb") as f:
            raw_img_bytes = f.read()
        height_result = _height_case_correct(raw_img_bytes, best_upper)
        if len(height_result) == 4 and height_result != best_upper:
            # 高度判断有明确的大小写意见，加入2票
            group_results.extend([height_result, height_result])
            _log(logging.INFO, "captcha height vote added: %s (2 extra votes)", height_result)
    except Exception:
        pass
    # 生成所有 2^n 逐字母大小写组合，按每个字母位的大写概率排序
    # 1) 计算每个字母位的大写概率
    letter_positions = []  # [(char_upper, P(uppercase)), ...]
    for i, ch in enumerate(best_upper):
        if ch.isalpha():
            upper_count = sum(1 for r in group_results if i < len(r) and r[i].isupper())
            p_upper = upper_count / len(group_results) if group_results else 0.5
            letter_positions.append((ch, p_upper))
        else:
            letter_positions.append((ch, None))  # 数字，无大小写
    # 2) 枚举所有组合（仅对字母位）
    n_letters = sum(1 for _, p in letter_positions if p is not None)
    all_combos = []
    for bits in range(2 ** n_letters):
        combo = []
        bit_idx = 0
        score = 1.0
        for ch, p_upper in letter_positions:
            if p_upper is None:
                combo.append(ch)  # 数字原样
            else:
                use_upper = bool((bits >> (n_letters - 1 - bit_idx)) & 1)
                combo.append(ch.upper() if use_upper else ch.lower())
                score *= (p_upper if use_upper else (1 - p_upper))
                bit_idx += 1
        all_combos.append(("".join(combo), score))
    # 3) 按概率降序排序（概率高的排前面）
    all_combos.sort(key=lambda x: -x[1])
    sorted_variants = [c for c, _ in all_combos]
    
    # 强制将高度修正结果作为首选变体 (Variant 1)
    if 'height_result' in locals() and height_result and len(height_result) == 4:
        if height_result in sorted_variants:
            sorted_variants.remove(height_result)
        sorted_variants.insert(0, height_result)
        _log(logging.INFO, "captcha prioritized height correct result: %s as Variant 1", height_result)
        
    best = sorted_variants[0]
    _log(logging.INFO, "captcha vote: %s (from %d valid results: %s), variants=%s", best, len(results), results, sorted_variants)
    # 保存验证码图片副本和识别记录到 captcha_debug/ 目录
    try:
        debug_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "captcha_debug")
        os.makedirs(debug_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        img_copy = os.path.join(debug_dir, f"captcha_{ts}.png")
        shutil.copy2(img_path, img_copy)
        # 写入识别记录（追加模式，含时间戳、识别结果、各方法结果）
        record_path = os.path.join(debug_dir, "recognize_log.txt")
        with open(record_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()}: "
                    f"result={best}, upper={best_upper}, "
                    f"valid_count={len(results)}, "
                    f"variants={sorted_variants}, "
                    f"results={results}\n")
    except Exception as e:
        _log(logging.DEBUG, "captcha debug save failed: %s", e)
    return best, sorted_variants


def _vlm_single_call(img_b64: str, api_key: str) -> str:
    """单次 VLM 调用，返回清洗后的识别结果（仅字母数字，取前4位）。"""
    import json as _json
    import httpx

    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    prompt_text = (
        "This is a captcha image containing exactly 4 alphanumeric characters. "
        "Carefully identify each character. Pay special attention to "
        "distinguishing uppercase from lowercase letters (e.g., O vs o, S vs s). "
        "Each character is independently randomized — the answer is NEVER a simple "
        "sequence like 1234, 0000, abcd, or AAAA. "
        "Output ONLY the 4 characters, nothing else. No spaces, no explanation."
    )
    payload = {
        "model": "qwen-vl-ocr-latest",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                    {
                        "type": "text",
                        "text": prompt_text,
                    },
                ],
            },
        ],
    }
    body = _json.dumps(payload, ensure_ascii=False).encode("utf-8")

    with httpx.Client(trust_env=False, timeout=30.0) as client:
        resp = client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        resp.raise_for_status()

    data = resp.json()
    raw = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    result = "".join(c for c in raw.strip() if c.isalnum())[:4]
    return result, raw.strip()


# 已知 VLM 幻觉模式：纯数字常见序列
_VLM_HALLUCINATION_PATTERNS = frozenset({
    "1234", "4321", "0000", "1111", "2222", "3333", "4444",
    "5555", "6666", "7777", "8888", "9999", "9876", "0123",
    "ABCD", "AAAA", "abcd",
})


def _captcha_recognize_vlm(img_path: str, api_key: str, call_count: int = 3) -> tuple[str, list[str]]:
    """使用视觉大模型（DashScope qwen-vl-ocr-latest）识别验证码图片。

    通过 httpx 直接请求 DashScope API（不依赖 openai 客户端），
    完全控制 JSON 序列化，避免 PyInstaller 打包后 ASCII 编码错误。
    多次调用投票选最优，过滤幻觉模式（如 1234/0000）。
    返回 (识别结果, 变体列表)，与 _captcha_recognize_multi 签名一致。
    """
    import base64
    import io
    from collections import Counter

    if not api_key:
        _log(logging.ERROR, "captcha VLM: API Key 未配置")
        return "", []

    try:
        # 图片预处理：放大 2x（LANCZOS），不覆盖原文件
        from PIL import Image
        with Image.open(img_path) as img:
            w, h = img.size
            img_upscaled = img.resize((w * 2, h * 2), Image.LANCZOS)
            buf = io.BytesIO()
            img_upscaled.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        vlm_call_count = max(1, int(call_count))
        raw_results = []
        for i in range(vlm_call_count):
            try:
                result, raw_text = _vlm_single_call(img_b64, api_key)
                _log(logging.INFO, "captcha VLM call %d/%d: %s (raw=%s)", i + 1, vlm_call_count, result, raw_text)
                if len(result) == 4:
                    raw_results.append(result)
            except Exception as e:
                _log(logging.WARNING, "captcha VLM call %d/%d failed: %s", i + 1, vlm_call_count, e)

        if not raw_results:
            _log(logging.ERROR, "captcha VLM: all %d calls produced no valid result", vlm_call_count)
            return "", []

        # 过滤幻觉：已知幻觉模式降权（从投票中移除）
        filtered_results = []
        for r in raw_results:
            if r.upper() in _VLM_HALLUCINATION_PATTERNS:
                _log(logging.WARNING, "captcha VLM: hallucination filtered: %s", r)
                continue
            filtered_results.append(r)

        # 如果全部被过滤为幻觉，不回退使用原始结果（输入已知的幻觉值必然失败，不如重新识别）
        if not filtered_results:
            _log(logging.WARNING, "captcha VLM: all %d results filtered as hallucination, returning empty (will re-recognize)",
                 len(raw_results))
            return "", []

        # 投票策略：按大写分组，选票数最多的组
        upper_groups = {}
        for r in filtered_results:
            key = r.upper()
            upper_groups.setdefault(key, []).append(r)

        best_upper = max(upper_groups, key=lambda k: len(upper_groups[k]))
        group_results = upper_groups[best_upper]

        # 逐字母大小写投票：每个字母位取出现最多的形式
        best_chars = []
        for i in range(4):
            char_votes = Counter(r[i] for r in group_results if i < len(r))
            best_chars.append(char_votes.most_common(1)[0][0])
        result = "".join(best_chars)

        _log(logging.INFO, "captcha VLM vote: %s (from %d calls, %d after filter: %s)",
             result, len(raw_results), len(filtered_results), filtered_results)

        # 生成变体列表（与 _captcha_recognize_multi 一致，供调用方逐个尝试）
        variants = []
        if len(result) == 4:
            variants.append(result)
            upper = result.upper()
            if upper != result:
                variants.append(upper)
            lower = result.lower()
            if lower != result and lower != upper:
                variants.append(lower)
            # 首字母大写变体
            titled = result[0].upper() + result[1:].lower() if len(result) > 1 else result
            if titled not in variants:
                variants.append(titled)
        return result, variants
    except Exception as e:
        _log(logging.ERROR, "captcha VLM failed: %s", e)
        return "", []


_captcha_local_fail_count = 0  # auto 模式下 ddddocr 连续失败计数（仅内存，重启清零）


def _captcha_recognize(img_path: str, mode: str = "local", vlm_api_key: str = "",
                        auto_fail_threshold: int = 3, vlm_call_count: int = 3) -> tuple[str, list[str]]:
    """验证码识别统一入口，根据 mode 分派到不同识别方式。

    Args:
        img_path: 验证码图片路径
        mode: 'local' 使用本地 ddddocr 投票，'vlm' 使用视觉大模型，
              'auto' ddddocr 优先，连续失败 auto_fail_threshold 次后降级 VLM
        vlm_api_key: mode='vlm'/'auto' 时的 DashScope API Key
        auto_fail_threshold: auto 模式下 ddddocr 连续失败多少次后切换 VLM（默认 3）
        vlm_call_count: VLM 模式下每张图调用大模型次数（默认 3）

    Returns:
        (识别结果, 变体列表)，与 _captcha_recognize_multi 签名一致
    """
    global _captcha_local_fail_count

    if mode == "vlm":
        return _captcha_recognize_vlm(img_path, vlm_api_key, call_count=vlm_call_count)

    if mode == "auto":
        # 已达失败阈值，直接走 VLM
        if _captcha_local_fail_count >= auto_fail_threshold:
            _log(logging.INFO, "captcha auto: local fail count=%d >= threshold=%d, fallback to VLM",
                 _captcha_local_fail_count, auto_fail_threshold)
            result, variants = _captcha_recognize_vlm(img_path, vlm_api_key, call_count=vlm_call_count)
            if len(result) == 4:
                _captcha_local_fail_count = 0  # VLM 成功，重置计数
            return result, variants

        # 未达阈值，先尝试 ddddocr
        result, variants = _captcha_recognize_multi(img_path)
        if len(result) == 4:
            _captcha_local_fail_count = 0  # ddddocr 成功，重置计数
            return result, variants

        # ddddocr 失败，累加计数
        _captcha_local_fail_count += 1
        _log(logging.INFO, "captcha auto: local failed, fail_count=%d/%d",
             _captcha_local_fail_count, auto_fail_threshold)

        # 刚好达到阈值，立即降级尝试 VLM
        if _captcha_local_fail_count >= auto_fail_threshold:
            _log(logging.INFO, "captcha auto: threshold reached, trying VLM immediately")
            result, variants = _captcha_recognize_vlm(img_path, vlm_api_key, call_count=vlm_call_count)
            if len(result) == 4:
                _captcha_local_fail_count = 0  # VLM 成功，重置计数
            return result, variants

        return result, variants

    # mode == "local"
    return _captcha_recognize_multi(img_path)


def _quick_check_captcha(trader):
    """快速检查是否存在验证码弹窗（不等待，立即返回）。

    用于高频轮询场景的预检，避免无弹窗时白白等待。
    返回找到的对话框 wrapper，未找到返回 None。
    """
    try:
        for w in trader.app.windows():
            try:
                if w.class_name() == "#32770" and w.is_visible():
                    for child in w.children(class_name="Static"):
                        if "验证码" in child.window_text():
                            return w
            except Exception:
                continue
    except Exception:
        pass
    return None


def _find_captcha_dialog(trader, timeout: float = 1.0):
    """遍历应用所有顶层窗口查找验证码对话框（带超时循环等待）。

    不依赖 top_window()，因为 _set_foreground(grid) 可能已将验证码
    对话框压到主窗口后面。返回找到的对话框 wrapper，未找到返回 None。
    """
    import time
    deadline = time.monotonic() + timeout
    while True:
        result = _quick_check_captcha(trader)
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


# ── 验证码通过后冷却（避免紧接的二次复制/置前再次触发弹窗）────────
_CAPTCHA_COOLDOWN_SECONDS = 4.0
_captcha_cooldown_until: float = 0.0


def mark_captcha_cooldown(seconds: float = _CAPTCHA_COOLDOWN_SECONDS) -> None:
    global _captcha_cooldown_until
    _captcha_cooldown_until = _time_module.monotonic() + seconds


def is_captcha_cooldown_active() -> bool:
    return _time_module.monotonic() < _captcha_cooldown_until


def _locate_captcha_dialog(trader, *, need_reg: bool) -> object | None:
    """查找验证码弹窗：先快检，未命中时再带超时轮询（避免刚弹出时漏检）。"""
    dlg = _quick_check_captcha(trader)
    if dlg is not None:
        return dlg
    timeout = 1.0 if need_reg else 0.5
    return _find_captcha_dialog(trader, timeout=timeout)


def should_skip_foreground_captcha(trader=None) -> bool:
    """bring_to_foreground 在冷却期内跳过重复验证码处理。

    若冷却期内验证码弹窗仍可见，不得跳过（否则需等下一次 API 才输入）。
    """
    if not is_captcha_cooldown_active():
        return False
    if trader is not None and _quick_check_captcha(trader) is not None:
        return False
    return True


from app.utils.grid_clipboard_context import (
    get_clipboard_page,
    get_requested_grid_page,
    mark_clipboard_page,
    records_match_grid_page,
    set_grid_copy_context,
)

from app.utils.grid_clipboard_context import (  # noqa: F401
    GRID_PAGE_FUNDS_STOCK,
    GRID_PAGE_HISTORY_ENTRUSTS,
    GRID_PAGE_TODAY_ENTRUSTS,
)


def _read_clipboard_safe() -> str:
    count = 5
    while count > 0:
        try:
            return pywinauto.clipboard.GetData()
        except Exception as e:
            count -= 1
            logger.exception("%s, retry ......", e)
    return ""


def _load_captcha_config() -> tuple[str, str, int, int]:
    mode, key, auto_th, vlm_n = "local", "", 3, 3
    try:
        from app.db import repository
        _cfg = repository.load_config()
        mode = _cfg.captcha_mode
        key = _cfg.vlm_api_key
        auto_th = _cfg.captcha_auto_fail_threshold
        vlm_n = _cfg.captcha_vlm_call_count
    except Exception:
        pass
    return mode, key, auto_th, vlm_n


def _clipboard_matches_requested_page(copy_self: Copy) -> bool:
    """剪贴板内容能否解析为当前请求的表格页（持仓/委托等）。"""
    content = _read_clipboard_safe()
    if not content:
        return False
    try:
        records = copy_self._format_grid_data(content)
    except Exception:
        return False
    if records is None:
        return False
    page = get_requested_grid_page()
    if page:
        return records_match_grid_page(records, page)
    return True


def _process_captcha_dialog(
    trader,
    dlg_wrapper,
    *,
    captcha_mode: str,
    vlm_api_key: str,
    auto_fail_threshold: int,
    vlm_call_count: int,
    log_prefix: str = "",
) -> bool:
    """截图识别并输入验证码，对话框消失返回 True。"""
    prefix = log_prefix or ""
    found = False
    attempt = 0
    for attempt in range(5):
        if attempt > 0:
            dlg_wrapper = _find_captcha_dialog(trader, timeout=1.0)
            if dlg_wrapper is None:
                logger.info(
                    "%scaptcha dialog gone after attempt %d, treating as success",
                    prefix,
                    attempt,
                )
                found = True
                Copy._need_captcha_reg = False
                mark_captcha_cooldown()
                break

        dlg = trader.app.window(handle=dlg_wrapper.handle)

        try:
            dlg.set_focus()
        except Exception:
            pass

        img_ctrl = None
        try:
            img_ctrl = dlg.child_window(control_id=0x965, class_name="Static")
            if not img_ctrl.exists():
                img_ctrl = None
        except Exception:
            img_ctrl = None

        if img_ctrl is None:
            for child in dlg.children(class_name="Static"):
                try:
                    if child.is_visible():
                        img_ctrl = child
                        _log(
                            logging.WARNING,
                            "%scaptcha image control fallback to first visible Static",
                            prefix,
                        )
                        break
                except Exception:
                    continue

        if img_ctrl is None:
            _log(logging.ERROR, "%scaptcha image control not found (attempt %d)", prefix, attempt)
            continue

        try:
            img_ctrl.capture_as_image().save(_CAPTCHA_IMG_PATH)
        except Exception as e:
            _log(logging.ERROR, "%scaptcha capture failed (attempt %d): %s", prefix, attempt, e)
            continue

        captcha_num, variants = _captcha_recognize(
            _CAPTCHA_IMG_PATH,
            mode=captcha_mode,
            vlm_api_key=vlm_api_key,
            auto_fail_threshold=auto_fail_threshold,
            vlm_call_count=vlm_call_count,
        )

        _log(
            logging.INFO,
            "%scaptcha result-->%s variants=%s (attempt %d)",
            prefix,
            captcha_num,
            variants,
            attempt,
        )

        if len(captcha_num) != 4:
            try:
                dlg.child_window(control_id=0x965, class_name="Static").click()
                trader.wait(0.2)
            except Exception:
                pass
            continue

        # 逐变体尝试：先尝试所有变体（大小写等），全部失败再刷新图片
        for vi, captcha_try in enumerate(variants):
            _log(
                logging.INFO,
                "%scaptcha trying variant %d/%d (attempt %d): %s",
                prefix,
                vi + 1,
                len(variants),
                attempt + 1,
                captcha_try,
            )

            editor = None
            try:
                editor = dlg.child_window(control_id=0x964, class_name="Edit")
                if not editor.exists():
                    editor = None
            except Exception:
                editor = None

            if editor is None:
                for child in dlg.children(class_name="Edit"):
                    try:
                        if child.is_visible():
                            editor = child
                            _log(
                                logging.WARNING,
                                "%scaptcha edit control fallback to first visible Edit",
                                prefix,
                            )
                            break
                    except Exception:
                        continue

            if editor is None:
                _log(logging.ERROR, "%scaptcha edit control not found (attempt %d)", prefix, attempt)
                break

            try:
                editor.set_focus()
            except Exception:
                pass
            trader.wait(0.1)
            try:
                _type_captcha_via_wm_char(editor, captcha_try)
            except Exception as e:
                _log(logging.ERROR, "%scaptcha type failed (attempt %d): %s", prefix, attempt, e)
                continue
            trader.wait(0.1)

            try:
                dlg.child_window(title="确定").click()
            except Exception:
                try:
                    dlg.type_keys("{ENTER}", set_foreground=False, pause=0.1)
                except Exception:
                    pass

            trader.wait(0.5)

            if _find_captcha_dialog(trader, timeout=0.5) is None:
                _log(
                    logging.INFO,
                    "%s验证码验证成功-->%s (variant %d/%d)",
                    prefix,
                    captcha_try,
                    vi + 1,
                    len(variants),
                )
                found = True
                Copy._need_captcha_reg = False
                mark_captcha_cooldown()
                break

            _log(
                logging.WARNING,
                "%scaptcha still present after input %s (variant %d/%d)",
                prefix,
                captcha_try,
                vi + 1,
                len(variants),
            )

        # 如果验证码已通过，跳出外层 attempt 循环
        if found:
            break

        # 所有变体均失败，刷新验证码图片重新识别
        _log(
            logging.INFO,
            "%scaptcha all %d variants failed for %s, clicking image to refresh",
            prefix,
            len(variants),
            captcha_num.upper(),
        )
        wait_time = 1.0 + attempt * 0.5
        trader.wait(wait_time)
        try:
            if img_ctrl is not None:
                img_ctrl.click()
                trader.wait(0.5)
            else:
                dlg.child_window(control_id=0x965, class_name="Static").click()
                trader.wait(0.5)
        except Exception:
            pass

    if not found:
        _log(
            logging.ERROR,
            "%scaptcha %d 次识别均失败，请手动处理验证码弹窗",
            prefix,
            attempt + 1,
        )
    return found


def _recopy_grid_after_captcha(copy_self: Copy, trader) -> None:
    """验证码通过后补复制：剪贴板已有效则跳过；补复制若再弹验证码则同函数内 OCR。"""
    _grid = getattr(copy_self, "_current_grid", None)
    if _grid is None:
        return

    page = get_requested_grid_page()
    if _clipboard_matches_requested_page(copy_self):
        setattr(copy_self, "_captcha_recopy_done", True)
        mark_clipboard_page(page)
        _log(
            logging.INFO,
            "clipboard_recopy_skip: clipboard already valid page=%s",
            page,
        )
        return

    mode, vlm_key, auto_th, vlm_n = _load_captcha_config()
    for recopy_round in range(2):
        try:
            _grid.type_keys("^A^C", set_foreground=False, pause=0.2)
            trader.wait(0.5)
        except Exception as e:
            _log(logging.WARNING, "clipboard_recopy_after_captcha failed: %s", e)
            return

        dlg = _locate_captcha_dialog(trader, need_reg=True)
        if dlg is not None:
            Copy._need_captcha_reg = True
            _log(
                logging.INFO,
                "captcha dialog detected after recopy (round %d)",
                recopy_round + 1,
            )
            if not _process_captcha_dialog(
                trader,
                dlg,
                captcha_mode=mode,
                vlm_api_key=vlm_key,
                auto_fail_threshold=auto_th,
                vlm_call_count=vlm_n,
                log_prefix="recopy ",
            ):
                return
            trader.wait(0.5)
            try:
                trader.close_pop_dialog()
            except Exception:
                pass

        if _clipboard_matches_requested_page(copy_self):
            setattr(copy_self, "_captcha_recopy_done", True)
            mark_clipboard_page(page)
            _log(
                logging.INFO,
                "clipboard_recopy_after_captcha: grid data valid page=%s round=%d",
                page,
                recopy_round + 1,
            )
            return

        _log(
            logging.WARNING,
            "clipboard_recopy: clipboard not valid after round %d page=%s",
            recopy_round + 1,
            page,
        )

    _log(logging.WARNING, "clipboard_recopy: gave up after 2 rounds page=%s", page)


def _copy_get_clipboard_data_patched(self: Copy) -> str:
    """增强版 _get_clipboard_data，修复验证码对话框被压到后面的问题。

    关键修复：
    - 用 _find_captcha_dialog() 遍历所有窗口，而非仅 top_window()
    - 仅在本轮实际处理并成功验证码后才补复制（^A^C）
    - 无弹窗时恢复 easytrader 的 _need_captcha_reg = False 免检语义
    """
    trader = self._trader
    captcha_resolved = False
    setattr(self, "_captcha_recopy_done", False)

    mode, vlm_key, auto_th, vlm_n = _load_captcha_config()

    dlg_wrapper = _locate_captcha_dialog(trader, need_reg=Copy._need_captcha_reg)
    if dlg_wrapper is not None:
        Copy._need_captcha_reg = True
    elif Copy._need_captcha_reg:
        Copy._need_captcha_reg = False

    if dlg_wrapper is not None:
        _log(logging.INFO, "captcha dialog detected")
        captcha_resolved = _process_captcha_dialog(
            trader,
            dlg_wrapper,
            captcha_mode=mode,
            vlm_api_key=vlm_key,
            auto_fail_threshold=auto_th,
            vlm_call_count=vlm_n,
        )
        if captcha_resolved:
            trader.wait(0.5)
            try:
                trader.close_pop_dialog()
            except Exception:
                pass

    if captcha_resolved:
        _recopy_grid_after_captcha(self, trader)
    elif getattr(self, "_current_grid", None) is not None:
        _log(logging.DEBUG, "clipboard_skip_recopy_no_captcha")

    return _read_clipboard_safe()


def _patched_copy_get(self: Copy, control_id: int):
    """增强版 Copy.get()：保存 grid 引用 + 冷却期内复用剪贴板 + 解析失败时有限重试。"""
    grid = self._get_grid(control_id)
    self._current_grid = grid
    self._set_foreground(grid)

    if is_captcha_cooldown_active():
        if _locate_captcha_dialog(self._trader, need_reg=False) is not None:
            _log(
                logging.INFO,
                "Copy.get: captcha visible during cooldown, skip clipboard reuse",
            )
        else:
            req_page = get_requested_grid_page()
            clip_page = get_clipboard_page()
            if req_page and req_page == clip_page:
                content = _read_clipboard_safe()
                if content:
                    result = self._format_grid_data(content)
                    if result is not None and records_match_grid_page(result, req_page):
                        _log(
                            logging.INFO,
                            "Copy.get: cooldown reuse clipboard without copy page=%s",
                            req_page,
                        )
                        return result
                    if result is not None:
                        _log(
                            logging.INFO,
                            "Copy.get: cooldown clipboard shape mismatch page=%s keys=%s, forcing copy",
                            req_page,
                            list(result[0].keys())[:12] if result else [],
                        )
            elif req_page and req_page != clip_page:
                _log(
                    logging.INFO,
                    "Copy.get: cooldown skip reuse (requested=%s clipboard=%s), forcing copy",
                    req_page,
                    clip_page,
                )

    for _copy_attempt in range(3):
        try:
            grid.type_keys("^A^C", set_foreground=False, pause=0.2)
            break
        except Exception as _copy_exc:
            if _copy_attempt >= 2:
                _log(
                    logging.ERROR,
                    "Copy.get: grid.type_keys failed after %d attempts: %s",
                    _copy_attempt + 1,
                    _copy_exc,
                )
                raise
            exc_name = type(_copy_exc).__name__
            if exc_name not in ("ElementNotVisible", "ElementNotEnabled"):
                raise
            _log(
                logging.WARNING,
                "Copy.get: grid not visible/enabled (%s), closing pop dialog and retrying (attempt %d)",
                exc_name,
                _copy_attempt + 1,
            )
            try:
                self._trader.close_pop_dialog()
            except Exception:
                pass
            self._trader.wait(0.5)
    content = self._get_clipboard_data()
    result = self._format_grid_data(content)
    if result is not None:
        mark_clipboard_page(get_requested_grid_page())
        return result

    content = _read_clipboard_safe()
    result = self._format_grid_data(content)
    if result is not None:
        mark_clipboard_page(get_requested_grid_page())
        _log(logging.DEBUG, "Copy.get: format retry from clipboard only")
        return result

    if not getattr(self, "_captcha_recopy_done", False):
        _log(logging.WARNING, "Copy.get: _format_grid_data returned None, retrying Ctrl+A/Ctrl+C once")
        try:
            grid.type_keys("^A^C", set_foreground=False, pause=0.2)
            self._trader.wait(0.5)
            content = self._get_clipboard_data()
            result = self._format_grid_data(content)
            if result is not None:
                mark_clipboard_page(get_requested_grid_page())
                return result
        except Exception as e:
            _log(logging.ERROR, "Copy.get: retry failed: %s", e)
    return result


def _patch_copy_strategy():
    """应用补丁"""
    if not hasattr(Copy, '_get_clipboard_data_original'):
        Copy._get_clipboard_data_original = Copy._get_clipboard_data
        Copy._get_clipboard_data = _copy_get_clipboard_data_patched
        logger.info("已应用 Copy 策略验证码补丁")
    if not hasattr(Copy, 'get_original'):
        Copy.get_original = Copy.get
        Copy.get = _patched_copy_get
        logger.info("已应用 Copy.get() 重复制补丁")


_patch_copy_strategy()


# ── pywinauto process_get_modules / process_module 补丁 ──────────────────────
# pywinauto 0.6.6 的 process_get_modules() except 子句未覆盖 OSError，
# 导致 GetModuleFileNameEx 对受保护系统进程抛出 OSError: [Errno 22] 时
# 异常透传至 Application.connect() / process_from_module()，最终表现为终端连接失败。
#
# 补丁策略（双重保险）：
# 1. process_module() 本身：将 OSError 加入 except，从源头吞掉
# 2. process_get_modules()：同步加入 OSError 到 except 子句
# 这样无论 pywinauto 内部通过哪条路径调用 process_module，都不会再抛出 OSError。

def _patch_pywinauto_process_get_modules():
    try:
        import win32process
        import win32gui
        from pywinauto import application as _pwa_app
        from pywinauto.application import ProcessNotFoundError, process_module

        # ── 补丁 1：process_module 从源头吞掉 OSError ──
        _orig_process_module = process_module

        def _patched_process_module(process_id):
            try:
                return _orig_process_module(process_id)
            except OSError:
                raise ProcessNotFoundError(
                    f"Process {process_id} module query failed (OSError)"
                )

        if not getattr(_pwa_app.process_module, '_patched_oserror', False):
            _pwa_app.process_module = _patched_process_module
            _pwa_app.process_module._patched_oserror = True
            # 同步替换当前模块的引用
            process_module = _patched_process_module
            logger.info("已应用 pywinauto process_module OSError 补丁")

        # ── 补丁 2：process_get_modules 也加入 OSError 到 except ──
        def _patched_process_get_modules():
            modules = []
            pids = win32process.EnumProcesses()
            for pid in pids:
                if pid != 0 and isinstance(pid, int):
                    try:
                        modules.append((pid, _pwa_app.process_module(pid), None))
                    except (win32gui.error, ProcessNotFoundError, OSError):
                        continue
            return modules

        if not getattr(_pwa_app.process_get_modules, '_patched_oserror', False):
            _pwa_app.process_get_modules = _patched_process_get_modules
            _pwa_app.process_get_modules._patched_oserror = True
            logger.info("已应用 pywinauto process_get_modules OSError 补丁")
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning("pywinauto OSError 补丁应用失败: %s", _e)


_patch_pywinauto_process_get_modules()


# ── ClientTrader._switch_left_menus 补丁 ──────────────────────────────────
# 原始 _switch_left_menus / _switch_left_menus_by_shortcut 中
# type_keys() 默认 set_foreground=True，会调用 SetForegroundWindow。
# 当验证码弹窗（模态 #32770）存在时，SetForegroundWindow 被拒绝导致异常。
# 补丁：改为 set_foreground=False，因为 _bring_to_foreground() 已在操作前
# 将主窗口置前，无需 type_keys 再次尝试。

def _patch_switch_left_menus():
    """补丁 _switch_left_menus / _switch_left_menus_by_shortcut，
    将 type_keys 的 set_foreground 改为 False，避免验证码弹窗时
    SetForegroundWindow 失败。
    """
    try:
        from easytrader import clienttrader

        _orig_switch = clienttrader.ClientTrader._switch_left_menus
        _orig_switch_by_shortcut = clienttrader.ClientTrader._switch_left_menus_by_shortcut

        def _patched_switch_left_menus(self_trader, path, sleep=0.2):
            self_trader.close_pop_dialog()
            self_trader._get_left_menus_handle().get_item(path).select()
            self_trader._app.top_window().type_keys('{F5}', set_foreground=False)
            self_trader.wait(sleep)

        def _patched_switch_left_menus_by_shortcut(self_trader, shortcut, sleep=0.5):
            self_trader.close_pop_dialog()
            self_trader._app.top_window().type_keys(shortcut, set_foreground=False)
            self_trader.wait(sleep)

        if getattr(clienttrader.ClientTrader._switch_left_menus, '_patched_set_foreground', False):
            return

        clienttrader.ClientTrader._switch_left_menus = _patched_switch_left_menus
        clienttrader.ClientTrader._switch_left_menus_by_shortcut = _patched_switch_left_menus_by_shortcut
        clienttrader.ClientTrader._switch_left_menus._patched_set_foreground = True
        clienttrader.ClientTrader._switch_left_menus_by_shortcut._patched_set_foreground = True
        clienttrader.ClientTrader._switch_left_menus_original = _orig_switch
        clienttrader.ClientTrader._switch_left_menus_by_shortcut_original = _orig_switch_by_shortcut
        logger.info("已应用 _switch_left_menus set_foreground=False 补丁")
    except Exception as _e:
        logging.getLogger(__name__).warning("_switch_left_menus 补丁应用失败: %s", _e)


_patch_switch_left_menus()


# ── ClientTrader.close_pop_dialog 补丁 ──────────────────────────────────
# 原始 close_pop_dialog 对所有非主窗口弹窗一律 w.close()。
# 若弹窗为验证码对话框，close() 会丢弃验证码而非正确处理，
# 且模态对话框可能无法被 close() 关闭，导致后续 type_keys 失败。
# 补丁：检测到验证码弹窗时先调用 _quick_check_captcha 识别处理，
# 处理成功后弹窗自然消失；非验证码弹窗仍走原始 close() 逻辑。

def _handle_captcha_in_close_pop(trader, dlg_wrapper) -> None:
    """在 close_pop_dialog 中处理验证码弹窗：截图识别 → 输入 → 点击确定。

    与 _copy_get_clipboard_data_patched 中的验证码处理逻辑一致，
    但作为独立函数供 close_pop_dialog 补丁调用。
    最多 8 轮，每轮只输入 1 个最佳结果。失败仅写日志，不抛异常。
    """
    from app.db import repository
    _cfg = repository.load_config()
    _captcha_mode = _cfg.captcha_mode
    _vlm_api_key = _cfg.vlm_api_key
    _captcha_auto_fail_threshold = _cfg.captcha_auto_fail_threshold
    _captcha_vlm_call_count = _cfg.captcha_vlm_call_count

    for attempt in range(8):
        if attempt > 0:
            dlg_wrapper = _find_captcha_dialog(trader, timeout=1.0)
            if dlg_wrapper is None:
                _log(logging.INFO, "close_pop_dialog captcha: dialog gone after attempt %d", attempt)
                return
        dlg = trader.app.window(handle=dlg_wrapper.handle)
        try:
            dlg.set_focus()
        except Exception:
            pass
        # 截图识别
        img_ctrl = None
        try:
            img_ctrl = dlg.child_window(control_id=0x965, class_name="Static")
            if not img_ctrl.exists():
                img_ctrl = None
        except Exception:
            img_ctrl = None
        if img_ctrl is None:
            for child in dlg.children(class_name="Static"):
                try:
                    if child.is_visible():
                        img_ctrl = child
                        break
                except Exception:
                    continue
        if img_ctrl is None:
            _log(logging.ERROR, "close_pop_dialog captcha: image control not found (attempt %d)", attempt)
            continue
        try:
            img_ctrl.capture_as_image().save(_CAPTCHA_IMG_PATH)
        except Exception as e:
            _log(logging.ERROR, "close_pop_dialog captcha: capture failed (attempt %d): %s", attempt, e)
            continue
        captcha_num, variants = _captcha_recognize(
            _CAPTCHA_IMG_PATH,
            mode=_captcha_mode,
            vlm_api_key=_vlm_api_key,
            auto_fail_threshold=_captcha_auto_fail_threshold,
            vlm_call_count=_captcha_vlm_call_count,
        )
        _log(logging.INFO, "close_pop_dialog captcha result-->%s variants=%s (attempt %d)", captcha_num, variants, attempt)
        if len(captcha_num) != 4:
            try:
                dlg.child_window(control_id=0x965, class_name="Static").click()
                trader.wait(0.2)
            except Exception:
                pass
            continue
        captcha_try = variants[0]
        _log(logging.INFO, "close_pop_dialog captcha trying best variant (attempt %d): %s", attempt+1, captcha_try)
        # 输入验证码
        editor = None
        try:
            editor = dlg.child_window(control_id=0x964, class_name="Edit")
            if not editor.exists():
                editor = None
        except Exception:
            editor = None
        if editor is None:
            for child in dlg.children(class_name="Edit"):
                try:
                    if child.is_visible():
                        editor = child
                        break
                except Exception:
                    continue
        if editor is None:
            _log(logging.ERROR, "close_pop_dialog captcha: edit control not found (attempt %d)", attempt)
            break
        try:
            editor.set_focus()
        except Exception:
            pass
        trader.wait(0.1)
        try:
            # 通过 WM_CHAR 逐字符输入，触发 EN_CHANGE 通知
            _type_captcha_via_wm_char(editor, captcha_try)
        except Exception as e:
            _log(logging.ERROR, "close_pop_dialog captcha: type failed (attempt %d): %s", attempt, e)
            continue
        trader.wait(0.1)
        # 点击确定
        try:
            dlg.child_window(title="确定").click()
        except Exception:
            try:
                dlg.type_keys("{ENTER}", set_foreground=False, pause=0.1)
            except Exception:
                pass
        trader.wait(0.5)
        # 验证：对话框消失即成功
        if _find_captcha_dialog(trader, timeout=0.5) is None:
            _log(logging.INFO, "close_pop_dialog 验证码验证成功-->%s (attempt %d)", captcha_try, attempt+1)
            mark_captcha_cooldown()
            return
        else:
            _log(logging.WARNING, "close_pop_dialog captcha still present after input %s (attempt %d)", captcha_try, attempt+1)
        # 刷新验证码图片
        wait_time = 1.0 + attempt * 0.5
        trader.wait(wait_time)
        try:
            if img_ctrl is not None:
                img_ctrl.click()
                trader.wait(0.5)
            else:
                dlg.child_window(control_id=0x965, class_name="Static").click()
                trader.wait(0.5)
        except Exception:
            pass
    _log(logging.ERROR, "close_pop_dialog captcha: 8 次识别均失败，请手动处理验证码弹窗")


def _patch_close_pop_dialog():
    """补丁 close_pop_dialog，检测验证码弹窗时先处理再关闭。"""
    try:
        from easytrader import clienttrader

        _orig_close = clienttrader.ClientTrader.close_pop_dialog

        def _patched_close_pop_dialog(self_trader):
            # 先检查是否存在验证码弹窗
            try:
                captcha_dlg = _locate_captcha_dialog(self_trader, need_reg=False)
                if captcha_dlg is not None:
                    _log(logging.INFO, "close_pop_dialog: captcha dialog detected, handling via OCR")
                    # 直接处理验证码（而非仅 return 跳过）
                    # 仅 return 会导致后续菜单导航和 Copy 操作被模态弹窗阻塞失败
                    try:
                        _handle_captcha_in_close_pop(self_trader, captcha_dlg)
                    except Exception as e:
                        _log(logging.ERROR, "close_pop_dialog: captcha handling failed: %s", e)
                    return  # 处理完毕（无论成败），不点取消
            except Exception:
                pass

            # 尝试处理普通提示弹窗 (如“连接重连失败”等)
            try:
                w = self_trader.app.top_window()
                if w is not None and self_trader._main.wrapper_object() != w.wrapper_object():
                    text = ""
                    try:
                        text = w.window_text() or ""
                        for child in w.children(class_name="Static"):
                            text += " " + (child.window_text() or "")
                    except Exception:
                        pass
                    
                    if "连接重连失败" in text or "提示" in text:
                        _log(logging.WARNING, "close_pop_dialog: detected prompt dialog '%s', trying to click '确定'", text.strip())
                        try:
                            btn = w.child_window(title="确定")
                            if btn.exists():
                                btn.click()
                                self_trader.wait(0.2)
                                return
                        except Exception:
                            try:
                                w.type_keys("{ENTER}", set_foreground=False)
                                self_trader.wait(0.2)
                                return
                            except Exception:
                                pass
            except Exception:
                pass

            # 非验证码弹窗：走原始 close() 逻辑
            _orig_close(self_trader)

        if getattr(clienttrader.ClientTrader.close_pop_dialog, '_patched_captcha', False):
            return

        clienttrader.ClientTrader.close_pop_dialog = _patched_close_pop_dialog
        clienttrader.ClientTrader.close_pop_dialog._patched_captcha = True
        clienttrader.ClientTrader.close_pop_dialog_original = _orig_close
        logger.info("已应用 close_pop_dialog 验证码弹窗补丁")
    except Exception as _e:
        logging.getLogger(__name__).warning("close_pop_dialog 补丁应用失败: %s", _e)


_patch_close_pop_dialog()


# ── ClientTrader._type_edit_control_keys 补丁 ──────────────────────────
# 原始 _type_edit_control_keys 在 use_type_keys=True 时走 type_keys，
# type_keys 内部使用 SendInput，依赖窗口前台状态。
# 当 SetForegroundWindow 失败时 SendInput 插入 0 事件导致 RuntimeError。
# 补丁：use_type_keys=True 时优先用 WM_CHAR 逐字符输入（与验证码输入一致），
# 不依赖窗口前台，仅在 WM_CHAR 失败时回退到原始 type_keys。

def _type_edit_via_wm_char(editor, text):
    """通过 WM_CHAR 逐字符输入到 Edit 控件，不依赖窗口焦点/前台状态。

    与 _type_captcha_via_wm_char 逻辑一致，但用于下单输入。
    WM_CHAR 触发 EN_CHANGE 通知，THS 客户端正确识别输入内容。
    """
    try:
        hwnd = editor.element_info.handle
    except Exception:
        hwnd = None
    if hwnd is None:
        editor.set_edit_text(text)
        return
    import win32con
    import win32gui
    # 全选后 WM_CHAR 逐字符输入覆盖（第一个字符替换全部选中内容）
    win32gui.SendMessage(hwnd, win32con.EM_SETSEL, 0, -1)
    for ch in text:
        win32gui.SendMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)


def _patch_type_edit_control_keys():
    """补丁 _type_edit_control_keys / type_edit_control_keys，
    use_type_keys=True 时用 WM_CHAR 替代 type_keys，避免 SendInput 失败。
    """
    try:
        from easytrader import clienttrader

        _orig_type_edit = clienttrader.ClientTrader._type_edit_control_keys
        _orig_type_edit_public = clienttrader.ClientTrader.type_edit_control_keys

        def _patched_type_edit_control_keys(self_trader, control_id, text):
            if not self_trader._editor_need_type_keys:
                self_trader._main.child_window(
                    control_id=control_id, class_name="Edit"
                ).set_edit_text(text)
            else:
                editor = self_trader._main.child_window(control_id=control_id, class_name="Edit")
                try:
                    _type_edit_via_wm_char(editor, text)
                except Exception:
                    # WM_CHAR 失败时回退到原始 type_keys
                    _log(logging.WARNING, "_type_edit_control_keys WM_CHAR failed, fallback to type_keys")
                    editor.select()
                    editor.type_keys(text)

        def _patched_type_edit_control_keys_public(self_trader, editor, text):
            if not self_trader._editor_need_type_keys:
                editor.set_edit_text(text)
            else:
                try:
                    _type_edit_via_wm_char(editor, text)
                except Exception:
                    _log(logging.WARNING, "type_edit_control_keys WM_CHAR failed, fallback to type_keys")
                    editor.select()
                    editor.type_keys(text)

        if getattr(clienttrader.ClientTrader._type_edit_control_keys, '_patched_wm_char', False):
            return

        clienttrader.ClientTrader._type_edit_control_keys = _patched_type_edit_control_keys
        clienttrader.ClientTrader.type_edit_control_keys = _patched_type_edit_control_keys_public
        clienttrader.ClientTrader._type_edit_control_keys._patched_wm_char = True
        clienttrader.ClientTrader.type_edit_control_keys._patched_wm_char = True
        clienttrader.ClientTrader._type_edit_control_keys_original = _orig_type_edit
        clienttrader.ClientTrader.type_edit_control_keys_original = _orig_type_edit_public
        logger.info("已应用 _type_edit_control_keys WM_CHAR 补丁")
    except Exception as _e:
        logging.getLogger(__name__).warning("_type_edit_control_keys 补丁应用失败: %s", _e)


_patch_type_edit_control_keys()


# ── PopDialogHandler._submit_by_shortcut 补丁 ──────────────────────────
# 原始 _submit_by_shortcut 先调用 SetForegroundWindow 再 type_keys("%Y")，
# SetForegroundWindow 失败时后续 type_keys(SendInput) 也会失败。
# 补丁：用 keybd_event 替代 SendInput(type_keys)，
# keybd_event 不受 SetForegroundWindow 限制，即使窗口不在前台也能发送按键。

def _patch_pop_dialog_handler():
    """补丁 PopDialogHandler._submit_by_shortcut，
    用 keybd_event 替代 type_keys("%Y")，避免 SendInput 失败。
    """
    try:
        from easytrader import pop_dialog_handler

        _orig_submit = pop_dialog_handler.PopDialogHandler._submit_by_shortcut

        def _patched_submit_by_shortcut(self_handler):
            """用 keybd_event 发送 Alt+Y，不依赖 SendInput/SetForegroundWindow。"""
            import win32con
            import win32api
            # VK_MENU = 0x12 (Alt), VK_Y = 0x59
            try:
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)    # Alt down
                win32api.keybd_event(0x59, 0, 0, 0)                 # Y down
                win32api.keybd_event(0x59, 0, win32con.KEYEVENTF_KEYUP, 0)  # Y up
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)  # Alt up
            except Exception:
                # keybd_event 失败时回退到原始方式
                _log(logging.WARNING, "_submit_by_shortcut keybd_event failed, fallback to original")
                try:
                    self_handler._set_foreground(self_handler._app.top_window())
                except Exception:
                    pass
                try:
                    self_handler._app.top_window().type_keys("%Y", set_foreground=False)
                except Exception:
                    pass

        if getattr(pop_dialog_handler.PopDialogHandler._submit_by_shortcut, '_patched_keybd', False):
            return

        pop_dialog_handler.PopDialogHandler._submit_by_shortcut = _patched_submit_by_shortcut
        pop_dialog_handler.PopDialogHandler._submit_by_shortcut._patched_keybd = True
        pop_dialog_handler.PopDialogHandler._submit_by_shortcut_original = _orig_submit
        logger.info("已应用 _submit_by_shortcut keybd_event 补丁")
    except Exception as _e:
        logging.getLogger(__name__).warning("_submit_by_shortcut 补丁应用失败: %s", _e)


_patch_pop_dialog_handler()
