import torch
from sklearn.metrics import f1_score


def _logits(output):
    """train()의 namedtuple / eval()의 Tensor 모두에서 예측 logits를 얻는다."""
    return output if torch.is_tensor(output) else output.logits


def accuracy(output, target):
    with torch.no_grad():
        pred = torch.argmax(_logits(output), dim=1)
        assert pred.shape[0] == len(target)
        correct = torch.sum(pred == target).item()
    return correct / len(target)


def macro_f1(output, target):
    """주어진 전체 logits/target에 대한 macro F1."""
    with torch.no_grad():
        pred = torch.argmax(_logits(output), dim=1)
        y_true = target.cpu().numpy()
        y_pred = pred.cpu().numpy()
    return float(f1_score(y_true, y_pred, average='macro', zero_division=0))
