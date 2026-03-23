import json
import argparse
import glob
import os
import subprocess
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from tqdm import tqdm

# --- 配置路径适配 ---
DEPLOY_DIR = "./"
# 修改点 1: 更新脚本名称
RUN_SCRIPT_PATH = os.path.join(DEPLOY_DIR, "qwen_coder_next.sh")


# --- 1. 参数设置 ---
def parse_args():
    parser = argparse.ArgumentParser(description="Distributed LLM Data Processor with Sandbox")

    # 路径参数
    parser.add_argument("--data_path", type=str, default="/home/ma-user/work/Synthesis/dataset")
    parser.add_argument("--output_path", type=str, default="/home/ma-user/work/Synthesis/result")
    parser.add_argument("--llm_model_path", type=str,
                        default="/home/ma-user/work/Synthesis/Qwen3-Coder-30B-A3B-Instruct")
    parser.add_argument("--sandbox_path", type=str, default="/home/ma-user/work/llm-agent")

    # vLLM 服务配置
    parser.add_argument("--max_num_seqs", type=int, default=12, help="vllm 最大部署并发")
    parser.add_argument("--max_model_len", type=int, default=124000)
    parser.add_argument("--model_name", type=str, default="qwen")
    parser.add_argument("--total_tasks", type=int, default=8, help="节点数量")
    parser.add_argument("--max_workers", type=int, default=12, help="最大请求并发")
    parser.add_argument("--base_url", type=str, default="http://127.0.0.1:8000/v1")
    parser.add_argument("--api_key", type=str, default="EMPTY")

    # --- 新增：llm-agent 运行参数 ---
    parser.add_argument("--max_execution_time", type=int, default=7200, help="Sandbox 最大执行时间(秒)")
    parser.add_argument("--max_tokens_per_call", type=int, default=4000, help="Sandbox 每次调用最大 token 数")
    parser.add_argument("--max_token_limit", type=int, default=120000, help="llm 最大上下文")
    parser.add_argument("--work_root_dir", type=str, default="/home/testbed", help="临时工作目录")

    return parser.parse_args()


# --- 新增：初始化 Sandbox 环境 ---
def init_sandbox_env(sandbox_path):
    print(f"--- 步骤 0: 初始化 Sandbox 环境 ---")
    if not os.path.exists(sandbox_path):
        print(f"错误: 找不到 Sandbox 目录 {sandbox_path}")
        sys.exit(1)

    try:
        print(f"正在安装 Sandbox 依赖: {sandbox_path}")
        # 使用 pip install -e . 安装项目
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."],
                       cwd=sandbox_path, check=True)
        print("Sandbox 依赖安装成功。")
    except subprocess.CalledProcessError as e:
        print(f"Sandbox 安装失败: {e}")
        sys.exit(1)


# --- 2. 服务启动与监控 ---
def wait_for_vllm_start(log_dir, success_message="Application startup complete.", timeout=600):
    """
    轮询监控 vLLM 日志
    """
    start_time = time.time()
    # 脚本中使用 tee 写入了 vllm_startup.log
    log_path = os.path.join(log_dir, "vllm_startup.log")

    print(f"正在监控 vLLM 日志 {log_path}，等待信号: '{success_message}'...")

    while time.time() - start_time < timeout:
        if not os.path.exists(log_path):
            time.sleep(5)
            continue

        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if success_message in content:
                    print(f"\n[SUCCESS] vLLM 启动成功!")
                    return True
                if "Traceback" in content or "Error:" in content:
                    # 打印最后几行错误信息
                    print(f"\n[ERROR] 检测到启动异常，请检查日志: {log_path}")
                    print("\n".join(content.splitlines()[-10:]))
        except Exception:
            pass

        sys.stdout.write('.')
        sys.stdout.flush()
        time.sleep(10)

    print(f"\n[TIMEOUT] vLLM 未能在 {timeout} 秒内启动。")
    return False


def start_vllm_service(args):
    print("--- 步骤 1: 启动 vLLM 部署服务 ---")
    if not os.path.exists(RUN_SCRIPT_PATH):
        print(f"致命错误: 找不到部署脚本 {RUN_SCRIPT_PATH}")
        sys.exit(1)

    # 准备环境变量
    env = os.environ.copy()
    env["BATCH_SIZE"] = str(args.max_num_seqs)
    env["MAX_MODEL_LEN"] = str(args.max_model_len)
    env["MODEL_SERVED_NAME"] = str(args.model_name)
    # 新增：将模型路径传递给 Shell
    env["LLM_MODEL_PATH"] = str(args.llm_model_path)

    # 打印启动配置以便确认
    print(f"[CONFIG] 模型路径: {args.llm_model_path}")
    print(f"[CONFIG] 模型服务名: {args.model_name}")

    subprocess.run(["chmod", "+x", RUN_SCRIPT_PATH])
    try:
        subprocess.Popen(
            ["bash", os.path.basename(RUN_SCRIPT_PATH)],
            cwd=DEPLOY_DIR,
            env=env
        )
    except Exception as e:
        print(f"启动脚本失败: {e}")
        sys.exit(1)

    if not wait_for_vllm_start(log_dir=DEPLOY_DIR):
        sys.exit(1)


# --- 3. 核心推理与 Sandbox 调度 ---
def process_single_item(client, item, args):
    try:
        messages = item.get("messages", [])
        if not messages: return None

        # 第一阶段：LLM 生成 Problem
        problem_res = client.chat.completions.create(
            model=args.model_name,
            messages=messages
        )
        problem_content = problem_res.choices[0].message.content.strip()

        # 第二阶段：调用 llm-agent (引用新增的 args 参数)
        sandbox_cmd = [
            "llm-agent", "run",
            "--local",
            "--query", problem_content,
            "--llm_name", f"hosted_vllm/{args.model_name}",
            "--llm_base_url", args.base_url,
            "--api_key", args.api_key,
            "--max_execution_time", str(args.max_execution_time),  # 转换为字符串
            "--max_tokens_per_call", str(args.max_tokens_per_call),  # 转换为字符串
            "--max_token_limit", str(args.max_token_limit),  # 转换为字符串
            "--output_root_dir", args.output_path,
            "--work_root_dir", args.work_root_dir,
        ]

        # 运行 Sandbox，使用列表形式确保 problem_content 中的特殊字符安全
        result_process = subprocess.run(
            sandbox_cmd,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )

        return {"status": "success" if result_process.returncode == 0 else "failed"}
    except Exception as e:
        print(f"处理出错: {e}")
        return {"status": "error", "message": str(e)}


def get_client(args):
    return OpenAI(api_key=args.api_key, base_url=args.base_url)


# --- 4. 任务分发 ---
def process_lines_across_files(all_files, args, task_index, total_tasks):
    # 1. 扫描与分发数据
    line_index = []
    global_line_num = 0
    for file_path in sorted(all_files):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_content in f:
                if line_content.strip() and global_line_num % total_tasks == task_index:
                    line_index.append({"content": line_content, "file": file_path})
                global_line_num += 1

    if not line_index: return

    client = OpenAI(api_key=args.api_key, base_url=args.base_url)

    # 2. 进度管理（简单断点续传）
    progress_log = os.path.join(args.output_path, f"progress_task_{task_index}.log")
    processed_count = 0
    if os.path.exists(progress_log):
        with open(progress_log, 'r') as f:
            processed_count = sum(1 for _ in f)

    current_tasks = line_index[processed_count:]

    # 3. 多线程执行
    with open(progress_log, 'a') as f_prog:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = {executor.submit(process_single_item, client, json.loads(l["content"]), args): l for l in
                       current_tasks}

            for future in tqdm(as_completed(futures), total=len(current_tasks), desc=f"Task {task_index}"):
                res = future.result()
                # 无论 Sandbox 运行结果如何，都记录一行代表该输入行已处理过
                f_prog.write("done\n")
                f_prog.flush()


# --- 5. 主程序 ---
def main():
    args = parse_args()
    task_index = int(os.getenv("VC_TASK_INDEX", "0"))

    # 0. 初始化 Sandbox
    init_sandbox_env(args.sandbox_path)
    # 1. 启动 vLLM 服务
    start_vllm_service(args)
    # 2. 准备输出 (注意：sandbox 也会写到这里)
    os.makedirs(args.output_path, exist_ok=True)

    all_files = [
        os.path.join(args.data_path, f) for f in os.listdir(args.data_path)
        if os.path.isfile(os.path.join(args.data_path, f)) and not f.startswith('.')
    ]
    all_files.sort()

    process_lines_across_files(all_files, args, task_index, args.total_tasks)
    print(f"Task {task_index} 完成。")


if __name__ == "__main__":
    main()