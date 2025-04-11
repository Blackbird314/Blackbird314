#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成网站字体子集脚本

从 /content 目录下的所有 .md 文件中提取中文和 ASCII 字符，
并为 LXGWBright-Medium.woff2 和 LXGWBright-MediumItalic.woff2 生成子集
"""

import os
import re
import glob
import shutil
import logging
from pathlib import Path
from fontTools.subset import main as subset_main

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 工作目录设置为脚本所在的根目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 配置项
CONTENT_DIR = "content"
OUTPUT_DIR = "static/fonts"
FONT_FILES = [
    "LXGWBright-Medium.woff2",
    "LXGWBright-MediumItalic.woff2"
]


def find_md_files():
    """查找所有 .md 文件"""
    md_files = glob.glob(f"{CONTENT_DIR}/**/*.md", recursive=True)
    logger.info(f"找到 {len(md_files)} 个 .md 文件")
    return md_files


def extract_characters(files):
    """从文件中提取中文和 ASCII 字符"""
    unique_chars = set()

    # 中文字符范围 (Unicode 4E00-9FFF)
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    # ASCII 字符范围 (Unicode 0020-007E)
    ascii_pattern = re.compile(r'[\u0020-\u007E]')

    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()

                # 提取字符
                chinese_chars = chinese_pattern.findall(content)
                ascii_chars = ascii_pattern.findall(content)

                # 添加到集合中
                unique_chars.update(chinese_chars)
                unique_chars.update(ascii_chars)

        except Exception as e:
            logger.error(f"处理文件 {file_path} 时出错: {e}")

    logger.info(f"提取了 {len(unique_chars)} 个唯一字符")
    return ''.join(unique_chars)


def create_font_subset(characters, source_font, output_font):
    """生成字体子集"""
    # 创建临时字符文件
    chars_file = "temp_chars.txt"
    with open(chars_file, 'w', encoding='utf-8') as f:
        f.write(characters)

    try:
        # 确保输出目录存在
        output_path = os.path.dirname(output_font)
        os.makedirs(output_path, exist_ok=True)

        # 运行字体子集工具
        subset_main([
            source_font,
            f'--output-file={output_font}',
            f'--text-file={chars_file}',
            '--flavor=woff2'
        ])

        # 计算大小减少
        original_size = os.path.getsize(source_font)
        subset_size = os.path.getsize(output_font)
        reduction = 100 - round((subset_size / original_size) * 100, 2)

        logger.info(f"已生成子集: {output_font}")
        logger.info(f"原始大小: {original_size/1024:.2f} KB")
        logger.info(f"子集大小: {subset_size/1024:.2f} KB (减小了 {reduction}%)")

        return True
    except Exception as e:
        logger.error(f"生成字体子集时出错: {e}")
        return False
    finally:
        # 删除临时文件
        if os.path.exists(chars_file):
            os.remove(chars_file)


def main():
    """主函数"""
    logger.info("开始生成字体子集...")

    # 查找所有 .md 文件
    md_files = find_md_files()
    if not md_files:
        logger.warning("未找到 .md 文件，退出")
        return

    # 提取字符
    characters = extract_characters(md_files)
    if not characters:
        logger.warning("未提取到任何字符，退出")
        return

    # 确保输出目录存在
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # 为每个字体创建子集
    for font_file in FONT_FILES:
        source_font = font_file
        output_font = os.path.join(OUTPUT_DIR, font_file)

        # 检查源字体是否存在
        if not os.path.exists(source_font):
            logger.error(f"源字体文件不存在: {source_font}")
            continue

        logger.info(f"处理字体: {font_file}")
        create_font_subset(characters, source_font, output_font)

    logger.info("字体子集生成完成")


if __name__ == "__main__":
    main()
