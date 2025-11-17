# -*- coding: utf-8 -*-
"""
CloudLab Profile for NVIDIA GH200 (nvidiagh) + H100

- 申请 nvidiagh 节点（默认 1 台）
- Ubuntu 22.04 镜像
- 开机自动安装 Docker 与 NVIDIA Container Toolkit
- 开启 GPU 持久化并做 nvidia-smi 自检
- 多节点时自动拉一条 LAN

兼容 Python 2（CloudLab Profile 解析器要求）。
"""

import geni.portal as portal
import geni.rspec.pg as pg

pc = portal.Context()
req = pc.makeRequestRSpec()

# ---------- Parameters ----------
p_nodes = pc.bindParameter(portal.Parameter(
    "nodes", portal.ParameterType.INTEGER, "Number of nodes",
    longDescription="How many nvidiagh nodes to allocate",
    defaultValue=1, min=1, max=16))

p_image = pc.bindParameter(portal.Parameter(
    "image_urn", portal.ParameterType.STRING, "Disk image URN",
    longDescription="Leave default unless you have a custom image",
    defaultValue="urn:publicid:IDN+utah.cloudlab.us+image+Canonical:ubuntu-22.04"
))

pc.verifyParameters()

# ---------- Setup script (run on each node) ----------
SETUP_BASH = r"""#!/usr/bin/env bash
set -euxo pipefail

echo "[INFO] Node: $(hostname)  Arch: $(uname -m)  Kernel: $(uname -r)"

# 0) Base
sudo apt-get update -y
sudo apt-get install -y git curl wget ca-certificates gnupg lsb-release \
  pciutils net-tools htop jq build-essential

# 1) Check driver
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "[INFO] nvidia-smi found:"
  nvidia-smi || true
else
  echo "[WARN] nvidia-smi not found. Use a GPU image or install driver."
fi

# 2) Docker
if ! command -v docker >/dev/null 2>&1; then
  echo "[INFO] Installing Docker..."
  sudo apt-get remove -y docker docker-engine docker.io containerd runc || true
  sudo apt-get install -y apt-transport-https software-properties-common
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo $UBUNTU_CODENAME) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io
  sudo usermod -aG docker $USER || true
fi

# 3) NVIDIA Container Toolkit
echo "[INFO] Installing NVIDIA Container Toolkit..."
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update -y
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker || true
sudo systemctl restart docker || true

# 4) Persistence + test
if command -v nvidia-smi >/dev/null 2>&1; then
  sudo nvidia-smi -pm 1 || true
  docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi || true
fi

# 5) Minor sysctl for DL
sudo bash -c 'cat >/etc/sysctl.d/99-dl-tuning.conf <<EOF
fs.inotify.max_user_watches=524288
fs.inotify.max_user_instances=1024
vm.max_map_count=1048576
EOF'
sudo sysctl --system || true

echo "[DONE] Setup complete."
"""

def add_node(idx):
    node = req.RawPC("node%d" % (idx + 1))
    node.hardware_type = "nvidiagh"
    node.disk_image = p_image.value

    # 将 SETUP_BASH 下发到节点并执行
    setup_cmd = "bash -lc 'cat >/tmp/setup.sh <<\"EOS\"\n" + SETUP_BASH + "\nEOS\nsudo bash /tmp/setup.sh'\n"
    node.addService(pg.Execute(shell="bash", command=setup_cmd))

    # 打印 NVMe 信息（可选）
    node.addService(pg.Execute(shell="bash", command="bash -lc \"echo '[INFO] Local NVMe:'; lsblk -o NAME,SIZE,MODEL || true\""))

    return node

nodes = []
for i in range(p_nodes.value):
    nodes.append(add_node(i))

# 多节点时加一条 LAN
if p_nodes.value > 1:
    lan = pg.LAN("lan")
    for j, n in enumerate(nodes):
        iface = n.addInterface("if%d" % (j + 1))
        lan.addInterface(iface)
    req.addResource(lan)

pc.printRequestRSpec(req)
