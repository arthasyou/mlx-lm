#!/bin/bash

# 设置数据路径和模型路径（你可以根据实际路径修改）
DATASET="data.txt"
MODEL_PATH="models/llama-7b-hf"
SAVE_PATH="models/checkpoints"

# 设置训练参数
CONTEXT_SIZE=1024
BATCH_SIZE=1
NUM_ITERS=500
LEARNING_RATE=1e-5
WEIGHT_DECAY=0.01
LR_WARMUP=100
STEPS_PER_REPORT=10
STEPS_PER_EVAL=100
SAVE_EVERY=500

# 执行训练：调用 mlx-lm 项目的 pt 子命令
python -m mlx_lm.pt \
  --dataset "$DATASET" \
  --model_path "$MODEL_PATH" \
  --save_path "$SAVE_PATH" \
  --context_size $CONTEXT_SIZE \
  --batch_size $BATCH_SIZE \
  --num_iters $NUM_ITERS \
  --learning_rate $LEARNING_RATE \
  --weight_decay $WEIGHT_DECAY \
  --lr_warmup $LR_WARMUP \
  --steps_per_report $STEPS_PER_REPORT \
  --steps_per_eval $STEPS_PER_EVAL \
  --save_every $SAVE_EVERY \
  --eval_test