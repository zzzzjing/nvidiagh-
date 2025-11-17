# -*- coding: utf-8 -*-
"""
CloudLab Profile for NVIDIA GH200 (nvidiagh) + H100
- Python 2 compatible
- 参数: nodes, image_urn
- 自动安装 Docker 与 NVIDIA Container Toolkit，开启持久化并自检
"""
import geni.portal as portal
import geni.rspec.pg as PG
import geni.rspec.igext as IG   # <-- Tour 在 igext 里

pc = portal.Context()
req = pc.makeRequestRSpec()

# -------- Parameters --------
pc.defineParameter("nodes", "Number of nodes",
                   portal.ParameterType.INTEGER, 1,
                   longDescription="How many nvidiagh nodes to allocate (1-16)")
pc.defineParameter("image_urn", "Disk image URN",
                   portal.ParameterType.STRING,
                   "urn:publicid:IDN+utah.cloudlab.us+image+Canonical:ubuntu-22.04",
                   longDescription="Keep default unless you have a custom image")
params = pc.bindParameters()

# -------- Safe Tour text (纯 ASCII，避免 XML 控制字符) --------
tour = IG.Tour()
tour.Description("Profile for NVIDIA GH200 (nvidiagh) node(s) with one H100 GPU.")
tour.Instructions(
    "After the experiment is ready, SSH to the node(s). "
    "Docker and the NVIDIA Container Toolkit will be installed automatically. "
    "Verify with: docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi"
)
req.addTour(tour)

# -------- Per-node setup script --------
SETUP_BASH = r"""#!/usr/bin/env bash
set -eux

echo "[INFO] Node: $(hostname)  Arch: $(uname -m)  Kernel: $(uname -r)"

# Base pkgs
sudo apt-get update -y
sudo apt-get install -y git curl wget ca-certificates gnupg lsb-release \
  pciutils net-tools htop jq build-essential apt-transport-https software-properties-common

# Check driver
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi || true
else
  echo "[WARN] nvidia-smi not found. Use a GPU-enabled image or install a driver."
fi

# Docker
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get remove -y docker docker-engine docker.io containerd runc || true
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo $UBUNTU_CODENAME) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io
  sudo usermod -aG docker $USER || true
fi

# NVIDIA Container Toolkit
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update -y
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker || true
sudo systemctl restart docker || true

# Persistence + test
if command -v nvidia-smi >/dev/null 2>&1; then
  sudo nvidia-smi -pm 1 || true
  docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi || true
fi

# Minor sysctl for DL
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
    node.disk_image = params.image_urn

    # 通过 Execute 下发脚本并执行
    cmd = "bash -lc 'cat >/tmp/setup.sh <<\"EOS\"\n" + SETUP_BASH + "\nEOS\nsudo bash /tmp/setup.sh'\n"
    node.addService(PG.Execute(shell="bash", command=cmd))

    # 可选: 打印 NVMe 信息
    node.addService(PG.Execute(shell="bash",
        command="bash -lc \"echo '[INFO] Local NVMe:'; lsblk -o NAME,SIZE,MODEL || true\""))
    return node

nodes = []
for i in range(int(params.nodes)):
    nodes.append(add_node(i))

# 多节点时拉一条 LAN
if int(params.nodes) > 1:
    lan = PG.LAN("lan")
    for j, n in enumerate(nodes):
        iface = n.addInterface("if%d" % (j + 1))
        lan.addInterface(iface)
    req.addResource(lan)

pc.printRequestRSpec(req)
