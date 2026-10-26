#pragma once
#include <string>
namespace cs2tool { std::string QtWidgetsSnapshot(int offset, int limit);
std::string QtOpenEditor(const std::string& editor, bool confirm);
std::string QtMenuActions(const std::string& window);
std::string QtHammerOpenDialog(bool confirm);
std::string QtHammerProbeAction(const std::string& action,const std::string& title,bool confirm);
std::string QtFileDialogMap(const std::string& path,bool confirm); }

namespace cs2tool { std::string QtHammerOutliner(); }
