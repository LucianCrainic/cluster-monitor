mod app;
mod config;
mod model;
mod slurm;
mod ui;

use std::path::PathBuf;

use anyhow::{Result, bail};
use clap::Parser;

#[derive(Parser)]
#[command(version, about)]
struct Args {
    #[arg(long, conflicts_with_all = ["demo", "config_path", "init_config"])]
    config: Option<PathBuf>,
    #[arg(long, conflicts_with_all = ["config_path", "init_config"])]
    demo: bool,
    #[arg(long, conflicts_with = "init_config")]
    config_path: bool,
    #[arg(long)]
    init_config: bool,
    #[arg(long, value_name = "ID")]
    cluster: Option<String>,
}

#[tokio::main(worker_threads = 2)]
async fn main() -> Result<()> {
    let args = Args::parse();
    if args.config_path {
        println!("{}", config::user_path()?.display());
        return Ok(());
    }
    if args.init_config {
        println!("Created {}", config::init()?.display());
        return Ok(());
    }
    let config = config::load(args.config.as_deref(), args.demo)?;
    let selected = match args.cluster {
        Some(id) => {
            let Some(index) = config.clusters.iter().position(|cluster| cluster.id == id) else {
                bail!("Unknown cluster ID");
            };
            index
        }
        None => 0,
    };
    app::run(config, selected).await
}
