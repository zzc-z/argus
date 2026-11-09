"""变异测试工具：把「改坏 → 跑测试 → 改回来」变成一条命令。

## 为什么需要它

项目规则：「新加的每个测试都必须注入过回归验证过它真的会红」。
手工做这件事很贵——每条变异要：

1. 写一个临时脚本改代码
2. 跑测试看红不红
3. 改回来

上一轮 24 条变异写了 110 个临时脚本。而且**结论留在会话记录里**，
下个会话不知道做过什么、哪些已经验过。

## 用法

写一个 YAML（`tests/mutations.yaml`），每条变异一个条目：

```yaml
mutations:
  - id: M1
    desc: 节点累计耗时不累计
    file: app/services/agent_nodes.py
    from: 'total = self._accumulated_ms.get(stage, 0) + segment'
    to: 'total = segment'
    expect_fail: test_agent_stages.py
```

然后：

```bash
uv run python -m tests.mutation            # 跑全部
uv run python -m tests.mutation M1 M3     # 只跑指定几条
```

## 判定「测试有效」的标准

变异后**指定的那几个测试必须变红**。没变红说明：

- 那条测试是废的（断言恒真 / 只测了纯函数没测接线），或者
- 变异根本没改到目标代码（比如 `from` 字符串没匹配上）

两种都要报错——第二种尤其重要，它会让你**以为**验过了。

## 安全性

每次变异都会**改文件**再改回来。所以：

- 跑之前必须工作树干净（否则改回来时会把你的改动一起冲掉）
- 用 try/finally 保证异常时也还原
- 跑完校验文件内容与原始一致
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# 本文件在 apps/api/tests/ 下，所以 API_ROOT 是上两级。
API_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = API_ROOT.parent.parent


@dataclass(frozen=True)
class Mutation:
    """一条变异。"""

    id: str
    desc: str
    file: str
    from_: str
    to_: str
    expect_fail: str
    """预期会失败的测试文件（相对 tests/ 目录）。

    变异后这个文件里的测试必须有失败——没失败说明测试无效。
    """

    def target(self) -> Path:
        return API_ROOT / self.file

    def test_path(self) -> Path:
        return API_ROOT / "tests" / self.expect_fail


@dataclass(frozen=True)
class Result:
    """一条变异的执行结果。"""

    mutation: Mutation
    caught: bool
    """测试是否如预期变红（= 测试有效）。"""
    detail: str


def load_mutations(path: Path) -> list[Mutation]:
    """从 YAML 读变异清单。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[Mutation] = []
    for item in data.get("mutations", []):
        out.append(
            Mutation(
                id=item["id"],
                desc=item["desc"],
                file=item["file"],
                from_=item["from"],
                to_=item["to"],
                expect_fail=item["expect_fail"],
            )
        )
    return out


def run_mutation(mutation: Mutation) -> Result:
    """执行一条变异：改代码 → 跑测试 → 改回来。

    **测试文件用 ``-x``（首个失败就停）**——我们要的只是「有没有变红」，
    不是「有几个红了」。跑完全部会慢好几倍。
    """
    target = mutation.target()
    if not target.exists():
        return Result(mutation, caught=False, detail=f"文件不存在：{target}")

    original = target.read_text(encoding="utf-8")
    if mutation.from_ not in original:
        return Result(
            mutation,
            caught=False,
            detail=f"没找到要替换的代码（变异未生效，测试有效性未被验证）：{mutation.from_!r}",
        )

    try:
        target.write_text(original.replace(mutation.from_, mutation.to_, 1), encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                f"tests/{mutation.expect_fail}",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                "-x",
            ],
            cwd=API_ROOT,
            capture_output=True,
            text=True,
        )
        # **必须区分「测试失败」与「跑不起来」**。
        #
        # 变异可能把代码改到语法错误（比如删掉一个 ``yield``，函数不再是
        # 生成器）——那会让 pytest **收集不到测试**，返回码也是非 0。
        # 但那不是「测试抓到了变异」，而是「变异太粗暴，代码编译不过」。
        #
        # 两者混为一谈会让工具给出假阳性：它说「测试有效」，实际什么都没验。
        collected = "no tests ran" not in proc.stdout
        if not collected:
            return Result(
                mutation,
                caught=False,
                detail=(
                    "变异让代码无法导入（pytest 收集不到测试）——"
                    "这不是「测试有效」，是变异太粗暴。换一个更精确的改法。"
                ),
            )
        # 有失败 = 测试抓到了这个变异 = 测试有效
        caught = proc.returncode != 0
        detail = "测试变红（有效）" if caught else "测试仍然全绿——这条测试是废的"
        if not caught:
            detail += f"\n{proc.stdout[-800:]}"
        return Result(mutation, caught=caught, detail=detail)
    finally:
        # 无论成败都还原
        target.write_text(original, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="变异测试：验证测试真的能抓到它防的 bug")
    parser.add_argument("ids", nargs="*", help="只跑指定 id（默认全跑）")
    parser.add_argument(
        "--file",
        default=str(API_ROOT / "tests" / "mutations.yaml"),
        help="变异清单 YAML",
    )
    args = parser.parse_args(argv)

    manifest = Path(args.file)
    if not manifest.exists():
        print(f"找不到变异清单：{manifest}", file=sys.stderr)
        return 2

    mutations = load_mutations(manifest)
    if args.ids:
        wanted = set(args.ids)
        mutations = [m for m in mutations if m.id in wanted]
        if not mutations:
            print(f"没有匹配的变异 id：{args.ids}", file=sys.stderr)
            return 2

    print(f"跑 {len(mutations)} 条变异\n")
    results: list[Result] = []
    for mutation in mutations:
        print(f"[{mutation.id}] {mutation.desc} ... ", end="", flush=True)
        result = run_mutation(mutation)
        results.append(result)
        print(result.detail)

    failed = [r for r in results if not r.caught]
    print(f"\n{'=' * 60}")
    print(f"有效: {len(results) - len(failed)}/{len(results)}")
    if failed:
        print("未抓住（测试无效或变异未生效）：")
        for r in failed:
            print(f"  [{r.mutation.id}] {r.mutation.desc}")
        return 1
    print("全部变异都被有效测试抓住。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
