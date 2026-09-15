from abc import ABC, abstractmethod

from app.engine.import_process.state import ImportGraphState
from app.engine.tool.logger import logger


class NodeBase(ABC):

    name: str = "node_base"

    def __init__(self):
        """
        强制子类设置name
        """
        if self.name == "node_base":
            raise ValueError(f"{self.__class__.__name__} 必须设置 name 属性")

    def __call__(self, state: ImportGraphState) -> ImportGraphState:

        try:

            logger.info(f"{self.name} 开始执行...")

            result = self.process(state)

            logger.info(f"{self.name} 结束执行...")

            return result

        except Exception as e:
            logger.error(f"{self.name} 执行失败：{e}")
            raise

    @abstractmethod
    def process(self: ImportGraphState) -> ImportGraphState:
        """
        节点的核心处理逻辑
        :return:
        """
        pass


