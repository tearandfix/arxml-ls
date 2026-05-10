import pytest
from lxml import etree

from arxml_ls.indexing import build_arxml_tree

# Minimal ARXML document used across all test modules.
# Line numbers (1-indexed, as lxml reports them):
#  1  <AUTOSAR>
#  2    <AR-PACKAGES>
#  3      <AR-PACKAGE>
#  4        <SHORT-NAME>Application</SHORT-NAME>
#  5        <AR-PACKAGES>
#  6          <AR-PACKAGE>
#  7            <SHORT-NAME>Components</SHORT-NAME>
#  8            <ELEMENTS>
#  9              <ADAPTIVE-APPLICATION-SW-COMPONENT-TYPE>
#  10               <SHORT-NAME>MyComponent</SHORT-NAME>
#  11             </ADAPTIVE-APPLICATION-SW-COMPONENT-TYPE>
#  12           </ELEMENTS>
#  13         </AR-PACKAGE>
#  14       </AR-PACKAGES>
#  15     </AR-PACKAGE>
#  16   </AR-PACKAGES>
#  17 </AUTOSAR>
ARXML_SRC = """\
<AUTOSAR>
  <AR-PACKAGES>
    <AR-PACKAGE>
      <SHORT-NAME>Application</SHORT-NAME>
      <AR-PACKAGES>
        <AR-PACKAGE>
          <SHORT-NAME>Components</SHORT-NAME>
          <ELEMENTS>
            <ADAPTIVE-APPLICATION-SW-COMPONENT-TYPE>
              <SHORT-NAME>MyComponent</SHORT-NAME>
            </ADAPTIVE-APPLICATION-SW-COMPONENT-TYPE>
          </ELEMENTS>
        </AR-PACKAGE>
      </AR-PACKAGES>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>"""


@pytest.fixture
def arxml_root():
    return etree.fromstring(ARXML_SRC.encode())


@pytest.fixture
def arxml_tree(arxml_root):
    return build_arxml_tree(arxml_root)
