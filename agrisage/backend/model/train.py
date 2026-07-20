"""
AgriSage FR-1 이미지 분류 모델 학습 스크립트.

PRD 8.1은 InceptionV3 + ImageNet Pretrained Transfer Learning을 명시한다.
이 환경에서는 pretrained 가중치 호스트(download.pytorch.org, huggingface.co)가
네트워크 정책상 차단되어 있어 ImageNet 사전학습 가중치를 받을 수 없다.
따라서 데모/로컬 테스트 목적으로 동일한 CNN 파이프라인 구조(conv feature
extractor + FC 분류 헤드)를 처음부터(from scratch) 학습한다. 실제 배포 시에는
사내에서 접근 가능한 미러 또는 사전 준비된 InceptionV3 가중치로 교체해
PRD 8.1 요구사항대로 전이학습을 적용해야 한다 (README 참고).
"""
import json
import os

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data", "split")
OUT_DIR = os.path.dirname(__file__)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

IMG_SIZE = 128
BATCH_SIZE = 16
EPOCHS = 20
LR = 1e-3


def build_dataloaders():
    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(IMG_SIZE, scale=(0.8, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(15),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    eval_tf = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    train_ds = datasets.ImageFolder(os.path.join(DATA_DIR, "train"), transform=train_tf)
    val_ds = datasets.ImageFolder(os.path.join(DATA_DIR, "val"), transform=eval_tf)
    test_ds = datasets.ImageFolder(os.path.join(DATA_DIR, "test"), transform=eval_tf)

    assert train_ds.classes == val_ds.classes == test_ds.classes

    return (
        DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=2),
        DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=2),
        DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=2),
        train_ds.classes,
    )


class AgriSageCNN(nn.Module):
    """Compact CNN: 4 conv blocks + global average pool + FC head."""

    def __init__(self, num_classes: int):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(128, 256, 3, padding=1), nn.BatchNorm2d(256), nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.4),
            nn.Linear(256, num_classes),
        )

    def forward(self, x):
        return self.classifier(self.features(x))


def build_model(num_classes: int) -> nn.Module:
    return AgriSageCNN(num_classes).to(DEVICE)


def run_epoch(model, loader, criterion, optimizer=None):
    is_train = optimizer is not None
    model.train() if is_train else model.eval()
    total_loss, correct, total = 0.0, 0, 0
    with torch.set_grad_enabled(is_train):
        for x, y in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            if is_train:
                optimizer.zero_grad()
            out = model(x)
            loss = criterion(out, y)
            if is_train:
                loss.backward()
                optimizer.step()
            total_loss += loss.item() * x.size(0)
            correct += (out.argmax(1) == y).sum().item()
            total += x.size(0)
    return total_loss / total, correct / total


def main():
    train_loader, val_loader, test_loader, classes = build_dataloaders()
    print(f"classes ({len(classes)}): {classes}")

    model = build_model(len(classes))
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    best_val_acc = 0.0
    for epoch in range(1, EPOCHS + 1):
        train_loss, train_acc = run_epoch(model, train_loader, criterion, optimizer)
        val_loss, val_acc = run_epoch(model, val_loader, criterion)
        print(
            f"epoch {epoch}/{EPOCHS} "
            f"train_loss={train_loss:.4f} train_acc={train_acc:.4f} "
            f"val_loss={val_loss:.4f} val_acc={val_acc:.4f}"
        )
        if val_acc >= best_val_acc:
            best_val_acc = val_acc
            torch.save(model.state_dict(), os.path.join(OUT_DIR, "best_model.pt"))

    model.load_state_dict(torch.load(os.path.join(OUT_DIR, "best_model.pt")))
    test_loss, test_acc = run_epoch(model, test_loader, criterion)
    print(f"TEST loss={test_loss:.4f} acc={test_acc:.4f}")

    with open(os.path.join(OUT_DIR, "classes.json"), "w") as f:
        json.dump(classes, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, "metrics.json"), "w") as f:
        json.dump(
            {"best_val_acc": best_val_acc, "test_acc": test_acc, "test_loss": test_loss,
             "img_size": IMG_SIZE, "note": "from-scratch CNN, no ImageNet pretrained weights (network policy)"},
            f,
            indent=2,
        )


if __name__ == "__main__":
    main()
