#ifndef RESOURCES_H
#define RESOURCES_H

#define RESOURCES_EXECUTABLE_DIRECTORY 	"D:/seminario/Seminario2025_ICI5541/FantasyMapGenerator/build"
#define RESOURCES_FONT_DATA_DIRECTORY 	"D:/seminario/Seminario2025_ICI5541/FantasyMapGenerator/build/fontdata"
#define RESOURCES_CITY_DATA_DIRECTORY 	"D:/seminario/Seminario2025_ICI5541/FantasyMapGenerator/build/citydata"
#define RESOURCES_FONT_DATA_RESOURCE 	"D:/seminario/Seminario2025_ICI5541/FantasyMapGenerator/build/fontdata/fontdata.json"
#define RESOURCES_CITY_DATA_RESOURCE 	"D:/seminario/Seminario2025_ICI5541/FantasyMapGenerator/build/citydata/countrycities.json"

#include <string>

namespace gen{
namespace resources {
    
extern std::string getExecutableDirectory();
extern std::string getFontDataDirectory();
extern std::string getCityDataDirectory();
extern std::string getFontDataResource();
extern std::string getCityDataResource();
    
}
}

#endif
