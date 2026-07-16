"""! @file exceptions.py
@brief CAN FD Offset 优化器的可定位领域异常。

@author 篠見由紀
"""


class CanfdOptimizerError(Exception):
    """! @brief 所有可向 CLI 用户展示的领域错误基类。"""


class ConfigurationError(CanfdOptimizerError):
    """! @brief 配置文件类型、范围或字段组合无效。"""


class InputFileError(CanfdOptimizerError):
    """! @brief 输入路径不存在、不可读或文件格式无效。"""


class MissingFieldError(InputFileError):
    """! @brief DBC 或 ARXML 中缺少构建内部模型所需的字段。"""


class DataConflictError(InputFileError):
    """! @brief 多个工程数据源对同一字段给出互相冲突的值。"""


class UnsupportedMessageError(InputFileError):
    """! @brief 报文帧类型或属性超出当前周期 CAN FD 范围。"""


class OptimizationError(CanfdOptimizerError):
    """! @brief 搜索状态不变量或优化输入无效。"""
