import os
import logging

logger = logging.getLogger(__name__)

class Isaac64:
    def __init__(self, seed_bytes: bytes):
        """
        初始化 Isaac64 发生器
        seed_bytes: 种子字节，通常是 64 字节的字符串 ASCII 字节或 32 字节的 HEX 解码字节
        """
        self.rsl = [0] * 256
        self.mem = [0] * 256
        self.a = 0
        self.b = 0
        self.c = 0
        
        # 填充种子到 rsl 中
        seed_len = len(seed_bytes)
        if seed_len > 0:
            # 每 8 个字节合成一个 64 位无符号整数
            for i in range(256):
                val = 0
                for j in range(8):
                    idx = (i * 8 + j) % seed_len
                    # 循环使用种子字节进行填充
                    val |= (seed_bytes[idx] << (j * 8))
                self.rsl[i] = val
        
        self.randinit(True)

    def randinit(self, flag: bool):
        # 黄金比例常数 0x9e3779b97f4a7c13
        a = b = c = d = e = f = g = h = 0x9e3779b97f4a7c13
        
        def mix():
            nonlocal a, b, c, d, e, f, g, h
            a = (a ^ (b << 9)) & 0xffffffffffffffff; d = (d + a) & 0xffffffffffffffff; b = (b + c) & 0xffffffffffffffff
            b = (b ^ (c >> 9)) & 0xffffffffffffffff; e = (e + b) & 0xffffffffffffffff; c = (c + d) & 0xffffffffffffffff
            c = (c ^ (d << 23)) & 0xffffffffffffffff; f = (f + c) & 0xffffffffffffffff; d = (d + e) & 0xffffffffffffffff
            d = (d ^ (e >> 15)) & 0xffffffffffffffff; g = (g + d) & 0xffffffffffffffff; e = (e + f) & 0xffffffffffffffff
            e = (e ^ (f << 14)) & 0xffffffffffffffff; h = (h + e) & 0xffffffffffffffff; f = (f + g) & 0xffffffffffffffff
            f = (f ^ (g >> 20)) & 0xffffffffffffffff; a = (a + f) & 0xffffffffffffffff; g = (g + h) & 0xffffffffffffffff
            g = (g ^ (h << 43)) & 0xffffffffffffffff; b = (b + g) & 0xffffffffffffffff; h = (h + a) & 0xffffffffffffffff
            h = (h ^ (a >> 9)) & 0xffffffffffffffff; c = (c + h) & 0xffffffffffffffff; a = (a + b) & 0xffffffffffffffff

        for _ in range(4):
            mix()
            
        for i in range(0, 256, 8):
            if flag:
                a = (a + self.rsl[i]) & 0xffffffffffffffff
                b = (b + self.rsl[i+1]) & 0xffffffffffffffff
                c = (c + self.rsl[i+2]) & 0xffffffffffffffff
                d = (d + self.rsl[i+3]) & 0xffffffffffffffff
                e = (e + self.rsl[i+4]) & 0xffffffffffffffff
                f = (f + self.rsl[i+5]) & 0xffffffffffffffff
                g = (g + self.rsl[i+6]) & 0xffffffffffffffff
                h = (h + self.rsl[i+7]) & 0xffffffffffffffff
            mix()
            self.mem[i] = a
            self.mem[i+1] = b
            self.mem[i+2] = c
            self.mem[i+3] = d
            self.mem[i+4] = e
            self.mem[i+5] = f
            self.mem[i+6] = g
            self.mem[i+7] = h
            
        if flag:
            for i in range(0, 256, 8):
                a = (a + self.mem[i]) & 0xffffffffffffffff
                b = (b + self.mem[i+1]) & 0xffffffffffffffff
                c = (c + self.mem[i+2]) & 0xffffffffffffffff
                d = (d + self.mem[i+3]) & 0xffffffffffffffff
                e = (e + self.mem[i+4]) & 0xffffffffffffffff
                f = (f + self.mem[i+5]) & 0xffffffffffffffff
                g = (g + self.mem[i+6]) & 0xffffffffffffffff
                h = (h + self.mem[i+7]) & 0xffffffffffffffff
                mix()
                self.mem[i] = a
                self.mem[i+1] = b
                self.mem[i+2] = c
                self.mem[i+3] = d
                self.mem[i+4] = e
                self.mem[i+5] = f
                self.mem[i+6] = g
                self.mem[i+7] = h

        self.isaac64()
        self.cnt = 256

    def isaac64(self):
        self.c = (self.c + 1) & 0xffffffffffffffff
        self.b = (self.b + self.c) & 0xffffffffffffffff
        for i in range(256):
            x = self.mem[i]
            mode = i & 3
            if mode == 0:
                self.a = self.a ^ (~(self.a << 21))
            elif mode == 1:
                self.a = self.a ^ (self.a >> 5)
            elif mode == 2:
                self.a = self.a ^ (self.a << 12)
            elif mode == 3:
                self.a = self.a ^ (self.a >> 33)
                
            self.a = (self.a & 0xffffffffffffffff)
            self.a = (self.mem[(i + 128) & 255] + self.a) & 0xffffffffffffffff
            self.mem[i] = y = (self.mem[(x >> 3) & 255] + self.a + self.b) & 0xffffffffffffffff
            self.b = (self.mem[(y >> 11) & 255] + x) & 0xffffffffffffffff
            self.rsl[i] = self.b
        self.cnt = 256

    def generate_keystream(self, length: int) -> bytes:
        """生成指定长度的密钥流字节序列"""
        stream = bytearray()
        words_needed = (length + 7) // 8
        words_generated = 0
        
        while words_generated < words_needed:
            if self.cnt == 0:
                self.isaac64()
            self.cnt -= 1
            word = self.rsl[255 - self.cnt]
            # 转换为 8 字节小端序
            for j in range(8):
                stream.append((word >> (j * 8)) & 0xff)
            words_generated += 1
            
        return bytes(stream[:length])

def decrypt_channel_video(encrypted_path: str, decrypted_path: str, decode_key: str) -> bool:
    """
    对微信视频号缓存或下载的视频进行 Isaac64 XOR 头部解密
    encrypted_path: 加密的原视频文件路径
    decrypted_path: 解密后的目标视频文件路径
    decode_key: 微信提供的解密密钥（支持 64字节 HEX 或者原 ASCII 字符串）
    """
    try:
        if not os.path.exists(encrypted_path):
            logger.error(f"[DEC] 加密文件不存在: {encrypted_path}")
            return False
            
        # 1. 尝试解析 decode_key 为字节种子
        # 如果是 64 字节的 hex 字符串，微信内部可能直接将其作为 ascii 字符串处理，
        # 但有些逆向版本将其 hex decode。这里兼容处理：
        # 我们优先认为它是 64 字节的 ASCII 字符串，转换为 bytes
        seed = decode_key.encode('utf-8')
        
        # 2. 如果是 64 字节长度且满足 hex，我们也提供 hex 解码后作为种子的后备测试（若直接解密后头部不符合 mp4 特征）
        # 视频号通常加密前 128KB (131072 字节)
        encrypt_len = 131072
        
        with open(encrypted_path, 'rb') as f:
            header_data = f.read(encrypt_len)
            remaining_data = f.read()
            
        if not header_data:
            logger.error("[DEC] 读取加密文件头部失败")
            return False
            
        actual_encrypt_len = len(header_data)
        
        # 3. 使用 ASCII 种子生成密钥流并尝试解密
        isaac = Isaac64(seed)
        keystream = isaac.generate_keystream(actual_encrypt_len)
        
        decrypted_header = bytes([b ^ k for b, k in zip(header_data, keystream)])
        
        # 验证解密后的头部是否具有 MP4 容器特征 (包含 'ftyp' 标志)
        # ftyp 通常在文件的前 4-12 字节中
        if b'ftyp' not in decrypted_header[:32]:
            # 如果不包含，尝试用 hex 解码后的字节做种子重新解密
            try:
                if len(decode_key) == 64:
                    hex_seed = bytes.fromhex(decode_key)
                    isaac_hex = Isaac64(hex_seed)
                    keystream_hex = isaac_hex.generate_keystream(actual_encrypt_len)
                    decrypted_header_hex = bytes([b ^ k for b, k in zip(header_data, keystream_hex)])
                    if b'ftyp' in decrypted_header_hex[:32]:
                        logger.info("[DEC] 识别到使用 HEX 解码后的种子解密成功")
                        decrypted_header = decrypted_header_hex
            except Exception as hex_err:
                logger.debug(f"[DEC] 尝试使用 HEX 种子解密出错: {hex_err}")
                
        # 写入解密后的文件
        with open(decrypted_path, 'wb') as f:
            f.write(decrypted_header)
            if remaining_data:
                f.write(remaining_data)
                
        logger.info(f"[DEC] 视频号解密成功，已输出至: {decrypted_path}")
        return True
    except Exception as e:
        logger.error(f"[DEC] 微信视频号解密失败: {e}", exc_info=True)
        return False
