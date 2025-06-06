# Copyright © 2023-2024 Apple Inc.

import math
import time
from functools import partial
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
from mlx.utils import tree_flatten

from .tokenizer_utils import load_tokenizer
from .utils import load_model


def to_samples(context_size, dataset):
    window_size = context_size + 1  # include target
    samples = dataset.size // window_size
    dataset = dataset[: samples * window_size]
    return mx.array(dataset.reshape(samples, -1))


def iterate_batches(batch_size, context_size, dataset):
    inputs = to_samples(context_size, dataset)
    s = 0
    while True:
        if s == 0:
            # Reset permutation:
            perm = mx.random.permutation(inputs.shape[0])
        ids = perm[s : s + batch_size]
        yield inputs[ids]
        s += batch_size
        if s >= inputs.shape[0]:
            s = 0


def main(args):
    batch_size = args.batch_size
    context_size = args.context_size
    steps_per_eval = args.steps_per_eval
    steps_per_report = args.steps_per_report

    tokenizer = load_tokenizer(Path(args.model_path))
    with open(args.dataset, "r", encoding="utf-8") as f:
        text = f.read()
    tokens = mx.array(tokenizer.encode(text), dtype=mx.int32)
    train = tokens
    valid = tokens[: len(tokens) // 10]
    test = tokens[: len(tokens) // 10]

    model, _ = load_model(Path(args.model_path), lazy=False)
    model.train()
    mx.eval(model.parameters())
    for name, param in tree_flatten(model.parameters()):
        if hasattr(param, "dtype") and param.dtype != mx.float32:
            model.update({name: mx.to(mx.float32, param)})
    nparams = sum(
        x.size for k, x in tree_flatten(model.parameters()) if "embedding" not in k
    )
    print(f"Training a transformer with {nparams / 1024**2:.3f} M parameters")

    def loss_fn(model, inputs, reduction="mean"):
        x, y = inputs[..., :-1], inputs[..., 1:]
        logits = model(x)
        return nn.losses.cross_entropy(logits, y, reduction=reduction)

    optimizer = optim.AdamW(
        learning_rate=args.learning_rate, weight_decay=args.weight_decay
    )

    def eval_fn(dataset):
        inputs = to_samples(context_size, dataset)
        loss = 0
        for s in range(0, inputs.shape[0], batch_size):
            losses = loss_fn(model, inputs[s : s + batch_size], reduction="sum")
            loss += losses.item()
        return loss / (inputs.size - inputs.shape[0])

    state = [model.state, optimizer.state]

    @partial(mx.compile, inputs=state, outputs=state)
    def step(inputs):
        loss_and_grad_fn = nn.value_and_grad(model, loss_fn)
        loss, grads = loss_and_grad_fn(model, inputs)
        optimizer.update(model, grads)
        return loss

    train_iterator = iterate_batches(batch_size, context_size, train)
    losses = []
    tic = time.perf_counter()
    for it, inputs in zip(range(args.num_iters), train_iterator):
        optimizer.learning_rate = min(1, it / args.lr_warmup) * args.learning_rate
        loss = step(inputs)
        mx.eval(state)
        losses.append(loss.item())
        if (it + 1) % steps_per_report == 0:
            train_loss = sum(losses) / len(losses)
            toc = time.perf_counter()
            print(
                f"Iter {it + 1}: Train loss {train_loss:.3f}, "
                f"It/sec {steps_per_report / (toc - tic):.3f}"
            )
            losses = []
            tic = time.perf_counter()
        if (it + 1) % steps_per_eval == 0:
            val_loss = eval_fn(valid)
            toc = time.perf_counter()
            print(
                f"Iter {it + 1}: "
                f"Val loss {val_loss:.3f}, "
                f"Val ppl {math.exp(val_loss):.3f}, "
                f"Val took {(toc - tic):.3f}s, "
            )
            tic = time.perf_counter()
        if args.save_every > 0 and (it + 1) % args.save_every == 0:
            save_path = Path(args.save_path) / f"checkpoint_{it+1:06d}.safetensors"
            mx.save_safetensors(
                str(save_path), dict(tree_flatten(model.trainable_parameters()))
            )
            print(f"[INFO] Saved checkpoint to {save_path}")

    final_path = Path(args.save_path) / "final.safetensors"
    mx.save_safetensors(
        str(final_path), dict(tree_flatten(model.trainable_parameters()))
    )
    print(f"[INFO] Saved final model to {final_path}")

    if args.eval_test:
        test_loss = eval_fn(test)
        test_ppl = math.exp(test_loss)
        print(f"Test loss {test_loss:.3f}, Test ppl {test_ppl:.3f}.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser("Train a decoder-only Transformer LM with MLX.")
    parser.add_argument("--gpu", action="store_true", help="Use the Metal back-end.")
    parser.add_argument("--seed", type=int, default=42, help="Seed for the RNGs.")
    parser.add_argument(
        "--dataset",
        type=str,
        default="ptb",
        help="Dataset to train and evaluate on.",
    )
    parser.add_argument(
        "--context_size",
        type=int,
        default=1024,
        help="Context size in tokens of the model.",
    )
    parser.add_argument("--batch_size", type=int, default=2, help="Minibatch size.")
    parser.add_argument(
        "--num_iters", type=int, default=100000, help="Iterations to train for."
    )
    parser.add_argument(
        "--learning_rate", type=float, default=3e-4, help="AdamW learning rate."
    )
    parser.add_argument(
        "--weight_decay", type=float, default=1e-5, help="Set the weight decay"
    )
    parser.add_argument(
        "--lr_warmup", type=int, default=200, help="LR linear warmup iterations"
    )
    parser.add_argument(
        "--steps_per_report",
        type=int,
        default=10,
        help="Number of training steps between loss reporting.",
    )
    parser.add_argument(
        "--steps_per_eval",
        type=int,
        default=1000,
        help="Number of training steps between validations.",
    )
    parser.add_argument(
        "--eval_test",
        action="store_true",
        help="Evaluate on the test set after training",
    )
    parser.add_argument(
        "--model_path",
        type=str,
        required=True,
        help="Path to model directory with config and weights",
    )
    parser.add_argument(
        "--save_path",
        type=str,
        required=True,
        help="Directory to save checkpoints and final model",
    )
    parser.add_argument(
        "--save_every",
        type=int,
        default=1000,
        help="Save model every N steps (0 to disable)",
    )
    args = parser.parse_args()
    if not args.gpu:
        mx.set_default_device(mx.cpu)
    main(args)
