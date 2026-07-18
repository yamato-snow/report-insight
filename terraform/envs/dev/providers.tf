provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "report-insight"
      Env       = var.env
      ManagedBy = "terraform"
    }
  }
}
