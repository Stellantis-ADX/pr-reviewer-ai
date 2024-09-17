FROM pytorch/pytorch:2.0.0-cuda11.7-cudnn8-devel

RUN export DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y zsh tmux wget curl git vim htop libssl-dev gcc unzip pkg-config ninja-build git-lfs

RUN curl -OL https://github.com/protocolbuffers/protobuf/releases/download/v21.12/protoc-21.12-linux-x86_64.zip
RUN unzip -o protoc-21.12-linux-x86_64.zip -d /usr/local bin/protoc
RUN unzip -o protoc-21.12-linux-x86_64.zip -d /usr/local 'include/*'
RUN rm -f protoc-21.12-linux-x86_64.zip

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y



# Add Rust to the PATH
ENV PATH="/root/.cargo/bin:${PATH}"

RUN rustup install 1.79.0 && rustup default 1.79.0


# Verify the installation
RUN echo rustc --version


RUN git clone https://github.com/huggingface/text-generation-inference/
RUN cd text-generation-inference && git checkout 8f22cb961ad1afaba1755b98fb4e5e81536c8971
RUN cd text-generation-inference && BUILD_EXTENSIONS=true make install-server
# should do it manually to 1.79.0 if not it falls down to 1.78.0
RUN cd text-generation-inference && BUILD_EXTENSIONS=true cd router && cargo +1.79.0 install --path .
RUN cd text-generation-inference && BUILD_EXTENSIONS=true make install-launcher

# Set environment variables
ENV MODEL_NAME=mistralai/Codestral-22B-v0.1
ENV HF_API_TOKEN=$HF_TOKEN

# Download the model
RUN mkdir -p /models && \
    export HUGGING_FACE_HUB_TOKEN=$HF_API_TOKEN && \
    text-generation-server download-weights $MODEL_NAME

# Expose the port the app runs on
EXPOSE 8000

# Set the working directory
WORKDIR /

# Entrypoint command
ENTRYPOINT ["sh", "-c", "text-generation-launcher --model-id $MODEL_NAME --num-shard 4 --port 8000 --hostname 0.0.0.0 --dtype float16 --json-output --max-input-length 2000"]

